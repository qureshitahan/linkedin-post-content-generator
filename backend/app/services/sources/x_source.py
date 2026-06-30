"""X (Twitter) source — wraps the existing secure X API client.

Demoted to an optional signal: X in 2026 is pay-per-use and its corpus skews
away from niche professional discourse. Only runs when configured.
"""

import logging
from typing import List

from app.services.sources.base import NormalizedPost
from app.services.x_api import XAPIError, x_api_service

logger = logging.getLogger(__name__)


class XSource:
    name = "x"

    @property
    def is_configured(self) -> bool:
        return x_api_service.is_configured

    async def search(self, query: str, max_results: int = 20) -> List[NormalizedPost]:
        if not self.is_configured:
            return []
        try:
            raw = await x_api_service.search_recent_posts(query, max_results=max_results)
        except XAPIError as e:
            logger.warning(f"X search failed for '{query}': {e}")
            return []

        posts: List[NormalizedPost] = []
        for p in raw:
            posts.append(
                {
                    "id": f"x-{p.get('id', '')}",
                    "source": self.name,
                    "text": p.get("text", ""),
                    "title": None,
                    "created_at": p.get("created_at"),
                    "author_name": p.get("author_name", "Unknown"),
                    "author_handle": p.get("author_handle", "unknown"),
                    "author_followers": p.get("author_followers", 0) or 0,
                    "author_verified": p.get("author_verified", False),
                    "post_url": p.get("post_url", ""),
                    "likes": p.get("likes", 0) or 0,
                    "retweets": p.get("retweets", 0) or 0,
                    "replies": p.get("replies", 0) or 0,
                    "comments": p.get("replies", 0) or 0,
                    "impressions": p.get("impressions"),
                }
            )
        return posts


x_source = XSource()
