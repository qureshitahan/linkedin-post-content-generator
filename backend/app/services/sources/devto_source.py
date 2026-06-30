"""Dev.to source via the free public API (no key, no auth).

Developer-written articles on machine learning, data science, healthcare tech,
and AI — a good complement to news RSS and Hacker News for practitioner content.
Tags are configurable via DEVTO_TAGS in .env.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import httpx

from app.config import settings
from app.services.sources.base import NormalizedPost

logger = logging.getLogger(__name__)

DEVTO_API = "https://dev.to/api/articles"


class DevtoSource:
    name = "devto"

    @property
    def is_configured(self) -> bool:
        return bool(settings.devto_tag_list)

    async def search(self, query: str, max_results: int = 20) -> List[NormalizedPost]:
        """Fetch recent top articles from configured tags. Query is used to
        pick the best-matching tag when possible."""
        tags = settings.devto_tag_list
        if not tags:
            return []

        # Prefer a tag that appears in the search query, else fetch all tags.
        q_lower = query.lower()
        matched = [t for t in tags if t.lower().replace("-", " ") in q_lower or t.lower() in q_lower]
        fetch_tags = matched[:3] if matched else tags[:5]

        results = await asyncio.gather(
            *[self._fetch_tag(tag, max_results) for tag in fetch_tags],
            return_exceptions=True,
        )

        posts: List[NormalizedPost] = []
        seen: set[str] = set()
        for res in results:
            if isinstance(res, Exception):
                continue
            for post in res:
                pid = post["id"]
                if pid in seen:
                    continue
                seen.add(pid)
                posts.append(post)

        return posts[:max_results]

    async def _fetch_tag(self, tag: str, max_results: int) -> List[NormalizedPost]:
        params = {"tag": tag, "top": settings.devto_days_window, "per_page": min(max_results, 30)}
        try:
            async with httpx.AsyncClient(timeout=20.0, trust_env=False) as client:
                resp = await client.get(
                    DEVTO_API,
                    params=params,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; ContentIntel/1.0)"},
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            logger.warning(f"Dev.to fetch failed for tag '{tag}': {e}")
            return []

        posts: List[NormalizedPost] = []
        for article in data:
            post = self._normalize(article, tag)
            if post:
                posts.append(post)
        return posts

    def _normalize(self, article: dict, tag: str) -> Optional[NormalizedPost]:
        article_id = article.get("id")
        title = (article.get("title") or "").strip()
        url = (article.get("url") or "").strip()
        if not article_id or not title or not url:
            return None

        description = (article.get("description") or "").strip()
        text = title if not description else f"{title}. {description[:220]}"

        created_iso = article.get("published_at") or article.get("created_at")
        if created_iso:
            try:
                dt = datetime.fromisoformat(created_iso.replace("Z", "+00:00"))
                created_iso = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                created_iso = None

        likes = int(article.get("public_reactions_count") or 0)
        comments = int(article.get("comments_count") or 0)
        user = article.get("user") or {}

        return {
            "id": f"devto-{article_id}",
            "source": self.name,
            "text": text,
            "title": title,
            "created_at": created_iso,
            "author_name": user.get("name") or user.get("username") or "Dev.to",
            "author_handle": user.get("username") or tag,
            "post_url": url,
            "likes": likes,
            "retweets": 0,
            "replies": comments,
            "comments": comments,
            "impressions": None,
        }


devto_source = DevtoSource()
