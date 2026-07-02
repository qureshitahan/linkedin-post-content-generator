import base64
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

X_API_BASE = "https://api.x.com/2"
X_API_V1_BASE = "https://api.x.com/1.1"
X_AUTH_BASES = ["https://api.x.com", "https://api.twitter.com"]
BEARER_PLACEHOLDER = "your_x_bearer_token_here"


class XAPIError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class XAPIService:
    """Secure wrapper for X/Twitter API v2 capabilities used in Phase 1."""

    def __init__(self):
        self.bearer_token = settings.x_bearer_token
        self.headers = {
            "Authorization": f"Bearer {self.bearer_token}",
            "User-Agent": "LinkedInContentIntelligence/1.0",
        }
        if self._has_app_credentials():
            try:
                self._refresh_bearer_token_sync()
                logger.info("X API bearer token refreshed from app credentials")
            except Exception as e:
                logger.warning(f"Could not refresh X bearer token on init: {e}")

    def _has_app_credentials(self) -> bool:
        return bool(settings.x_api_key and settings.x_api_secret)

    @property
    def is_configured(self) -> bool:
        has_bearer = bool(self.bearer_token and self.bearer_token != BEARER_PLACEHOLDER)
        return has_bearer or self._has_app_credentials()

    def _refresh_bearer_token_sync(self) -> None:
        if not self._has_app_credentials():
            raise XAPIError(
                "X API bearer token is invalid. Add X_API_KEY and X_API_SECRET to .env, "
                "or regenerate the bearer token in the X Developer Portal."
            )

        cred = base64.b64encode(
            f"{settings.x_api_key}:{settings.x_api_secret}".encode()
        ).decode()

        for auth_base in X_AUTH_BASES:
            response = httpx.post(
                f"{auth_base}/oauth2/token",
                headers={
                    "Authorization": f"Basic {cred}",
                    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                },
                data="grant_type=client_credentials",
                timeout=30.0,
                trust_env=False,
            )
            if response.status_code == 200:
                token = response.json().get("access_token")
                if token:
                    self.bearer_token = token
                    self.headers["Authorization"] = f"Bearer {token}"
                    return

        raise XAPIError(
            f"Failed to obtain X API bearer token ({response.status_code}). "
            "Check X_API_KEY and X_API_SECRET in your .env file."
        )

    async def _refresh_bearer_token(self) -> None:
        self._refresh_bearer_token_sync()

    async def _request(
        self,
        method: str,
        url: str,
        params: Optional[Dict] = None,
        _retried: bool = False,
    ) -> Dict:
        if not self.is_configured:
            raise XAPIError("X API is not configured")

        try:
            async with httpx.AsyncClient(timeout=30.0, trust_env=False, proxy=None) as client:
                response = await client.request(method, url, headers=self.headers, params=params)
        except httpx.HTTPError as e:
            raise XAPIError(f"X API connection failed: {e}") from e

        if response.status_code == 401 and not _retried and self._has_app_credentials():
            await self._refresh_bearer_token()
            return await self._request(method, url, params, _retried=True)

        if response.status_code == 429:
            raise XAPIError("X API rate limit exceeded. Try again later.", 429)

        if response.status_code >= 400:
            detail = response.text[:500]
            if response.status_code == 401:
                raise XAPIError(
                    "X API authentication failed. Regenerate your bearer token or verify "
                    "X_API_KEY / X_API_SECRET in .env.",
                    401,
                )
            if response.status_code == 403:
                if "attached to a Project" in response.text:
                    raise XAPIError(
                        "X API 403: Your app must be attached to a Project in the X Developer Portal. "
                        "Go to developer.x.com → Projects → create or open a project → add your app → "
                        "then regenerate keys if needed.",
                        403,
                    )
                raise XAPIError(
                    "X API access denied (403). Check app permissions and credits in the X Developer Portal.",
                    403,
                )
            raise XAPIError(f"X API error ({response.status_code}): {detail}", response.status_code)

        return response.json()

    async def get_recent_post_count(self, query: str) -> int:
        """
        Recent Post Counts - check volume before pulling full posts.
        https://developer.x.com/en/docs/twitter-api/tweets/counts/api-reference/get-tweets-counts-recent
        """
        url = f"{X_API_BASE}/tweets/counts/recent"
        params = {
            "query": query,
            "granularity": "day",
        }
        data = await self._request("GET", url, params)

        total = 0
        for bucket in data.get("data", []):
            total += bucket.get("tweet_count", 0)
        return total

    async def search_recent_posts(self, query: str, max_results: int = 20) -> List[Dict]:
        """
        Recent Search - pull posts from the last 7 days.
        https://developer.x.com/en/docs/twitter-api/tweets/search/api-reference/get-tweets-search-recent
        """
        return await self._search_recent(
            query=f"{query} -is:retweet -is:reply lang:en",
            max_results=max_results,
        )

    async def search_research_buzz(
        self, query: str, max_results: int = 20, min_likes: Optional[int] = None,
        min_impressions: Optional[int] = None,
    ) -> List[Dict]:
        """Find high-traction X posts that link to research papers.

        Requires a scholarly URL in the tweet (arxiv, bioRxiv, DOI, etc.) so
        viral news accounts don't pollute research buzz.
        """
        min_likes = min_likes if min_likes is not None else settings.x_research_min_likes
        paper_links = (
            "url:arxiv.org OR url:biorxiv.org OR url:medrxiv.org OR "
            "url:doi.org OR url:nature.com OR url:science.org OR url:cell.com OR "
            "url:pubmed.ncbi.nlm.nih.gov"
        )
        x_query = f"({query}) ({paper_links}) -is:retweet -is:reply lang:en"
        raw = await self._search_recent(query=x_query, max_results=max(max_results * 3, 30))
        filtered = [p for p in raw if (p.get("likes") or 0) >= min_likes]
        if min_impressions and min_impressions > 0:
            filtered = [
                p for p in filtered
                if (p.get("impressions") or 0) >= min_impressions
                or (p.get("likes") or 0) >= min_likes
            ]
        filtered.sort(
            key=lambda p: (p.get("likes") or 0) + (p.get("retweets") or 0) * 3,
            reverse=True,
        )
        return filtered[:max_results]

    async def _search_recent(self, query: str, max_results: int = 20) -> List[Dict]:
        start_time = (datetime.now(timezone.utc) - timedelta(days=7)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

        url = f"{X_API_BASE}/tweets/search/recent"
        params = {
            "query": query,
            "max_results": max(10, min(max_results, 100)),
            "start_time": start_time,
            "sort_order": "relevancy",
            "tweet.fields": "created_at,public_metrics,author_id,text",
            "expansions": "author_id",
            "user.fields": "name,username,public_metrics,verified",
        }

        data = await self._request("GET", url, params)

        users = {}
        for user in data.get("includes", {}).get("users", []):
            users[user["id"]] = user

        posts = []
        for tweet in data.get("data", []):
            author = users.get(tweet.get("author_id", ""), {})
            metrics = tweet.get("public_metrics", {})
            author_metrics = author.get("public_metrics", {})
            posts.append(
                {
                    "id": tweet["id"],
                    "text": tweet.get("text", ""),
                    "created_at": tweet.get("created_at"),
                    "author_name": author.get("name", "Unknown"),
                    "author_handle": author.get("username", "unknown"),
                    "author_followers": author_metrics.get("followers_count", 0),
                    "author_verified": author.get("verified", False),
                    "post_url": f"https://x.com/{author.get('username', 'i')}/status/{tweet['id']}",
                    "likes": metrics.get("like_count", 0),
                    "retweets": metrics.get("retweet_count", 0),
                    "replies": metrics.get("reply_count", 0),
                    "impressions": metrics.get("impression_count"),
                }
            )

        return posts

    async def get_trends_by_location(self, woeid: Optional[int] = None) -> List[Dict]:
        """
        Trends by Location - optional broad signal (v1.1 endpoint).
        https://developer.x.com/en/docs/twitter-api/v1/trends/trends-for-location/api-reference/get-trends-place
        """
        woeid = woeid or settings.x_trends_woeid
        url = f"{X_API_V1_BASE}/trends/place.json"
        params = {"id": woeid}

        data = await self._request("GET", url, params)

        trends = []
        if data and isinstance(data, list) and len(data) > 0:
            for trend in data[0].get("trends", [])[:20]:
                trends.append(
                    {
                        "name": trend.get("name", ""),
                        "tweet_volume": trend.get("tweet_volume"),
                        "url": trend.get("url"),
                    }
                )
        return trends


x_api_service = XAPIService()
