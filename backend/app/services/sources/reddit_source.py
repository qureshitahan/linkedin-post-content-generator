"""Reddit source via the official Data API (free tier, OAuth required).

Highest-value source for professional/niche discourse (marketing, analytics,
ad tech, data engineering, etc.) that does NOT trend on X.

Setup (free, non-commercial):
  1. https://www.reddit.com/prefs/apps -> "create another app" -> type "script"
  2. Put the client id + secret in .env as REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET
  3. Optionally set REDDIT_USERNAME / REDDIT_PASSWORD for a script app (recommended),
     otherwise app-only client_credentials is attempted.

If credentials are absent the source disables itself gracefully.
"""

import logging
import time
from datetime import datetime, timezone
from typing import List, Optional

import httpx

from app.config import settings
from app.services.sources.base import NormalizedPost

logger = logging.getLogger(__name__)

REDDIT_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
REDDIT_API_BASE = "https://oauth.reddit.com"
PLACEHOLDERS = {
    "",
    "your_reddit_client_id_here",
    "your_reddit_client_secret_here",
    "your_reddit_username_here",
    "your_reddit_password_here",
}


class RedditSource:
    name = "reddit"

    def __init__(self):
        self._token: Optional[str] = None
        self._token_expiry: float = 0.0

    def _clean(self, value: str) -> str:
        return value if value and value not in PLACEHOLDERS else ""

    @property
    def client_id(self) -> str:
        return self._clean(settings.reddit_client_id)

    @property
    def client_secret(self) -> str:
        return self._clean(settings.reddit_client_secret)

    @property
    def username(self) -> str:
        return self._clean(settings.reddit_username)

    @property
    def password(self) -> str:
        return self._clean(settings.reddit_password)

    @property
    def user_agent(self) -> str:
        return settings.reddit_user_agent or "LinkedInContentIntelligence/1.0"

    @property
    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    async def _get_token(self, client: httpx.AsyncClient) -> Optional[str]:
        if self._token and time.time() < self._token_expiry - 60:
            return self._token

        if self.username and self.password:
            data = {
                "grant_type": "password",
                "username": self.username,
                "password": self.password,
            }
        else:
            data = {"grant_type": "client_credentials"}

        try:
            resp = await client.post(
                REDDIT_TOKEN_URL,
                data=data,
                auth=(self.client_id, self.client_secret),
                headers={"User-Agent": self.user_agent},
            )
            resp.raise_for_status()
            payload = resp.json()
        except httpx.HTTPError as e:
            logger.warning(f"Reddit auth failed: {e}")
            return None

        token = payload.get("access_token")
        if not token:
            logger.warning("Reddit auth returned no access_token")
            return None

        self._token = token
        self._token_expiry = time.time() + int(payload.get("expires_in", 3600))
        return token

    async def search(self, query: str, max_results: int = 20) -> List[NormalizedPost]:
        return await self._search(query, subreddit=None, max_results=max_results)

    async def search_subreddit(
        self, query: str, subreddit: str, max_results: int = 15
    ) -> List[NormalizedPost]:
        return await self._search(query, subreddit=subreddit, max_results=max_results)

    async def _search(
        self, query: str, subreddit: Optional[str], max_results: int
    ) -> List[NormalizedPost]:
        if not self.is_configured:
            return []

        async with httpx.AsyncClient(timeout=20.0, trust_env=False) as client:
            token = await self._get_token(client)
            if not token:
                return []

            if subreddit:
                url = f"{REDDIT_API_BASE}/r/{subreddit}/search"
                params = {
                    "q": query,
                    "restrict_sr": "1",
                    "sort": "top",
                    "t": "week",
                    "limit": max(5, min(max_results, 25)),
                    "type": "link",
                }
            else:
                url = f"{REDDIT_API_BASE}/search"
                params = {
                    "q": query,
                    "sort": "top",
                    "t": "week",
                    "limit": max(5, min(max_results, 25)),
                    "type": "link",
                }

            try:
                resp = await client.get(
                    url,
                    params=params,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "User-Agent": self.user_agent,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPError as e:
                logger.warning(
                    f"Reddit search failed for '{query}'"
                    f"{f' in r/{subreddit}' if subreddit else ''}: {e}"
                )
                return []

        posts: List[NormalizedPost] = []
        for child in data.get("data", {}).get("children", []):
            d = child.get("data", {})
            post_id = d.get("id")
            if not post_id:
                continue

            title = d.get("title", "")
            selftext = d.get("selftext", "") or ""
            text = title if not selftext else f"{title}\n\n{selftext[:600]}"

            created_iso = None
            created_utc = d.get("created_utc")
            if created_utc:
                created_iso = datetime.fromtimestamp(
                    created_utc, tz=timezone.utc
                ).strftime("%Y-%m-%dT%H:%M:%SZ")

            author = d.get("author", "unknown")
            sub = d.get("subreddit", "")
            score = int(d.get("score") or 0)
            num_comments = int(d.get("num_comments") or 0)
            permalink = d.get("permalink", "")

            posts.append(
                {
                    "id": f"reddit-{post_id}",
                    "source": self.name,
                    "text": text,
                    "title": title,
                    "created_at": created_iso,
                    "author_name": f"u/{author}",
                    "author_handle": f"r/{sub}" if sub else author,
                    "post_url": f"https://www.reddit.com{permalink}" if permalink else "",
                    "likes": score,
                    "retweets": 0,
                    "replies": num_comments,
                    "comments": num_comments,
                    "impressions": None,
                }
            )

        return posts


reddit_source = RedditSource()
