"""X Research Buzz source — high-traction tweets announcing research papers.

Researchers often post on X when they publish a breakthrough ("excited to share
our new paper on..."). This source specifically hunts those posts by combining
topic queries with paper URLs (arxiv, biorxiv, doi) and announcement language,
filtered by minimum likes so only posts with real traction surface.

Requires X API credentials (same as the regular x source).
"""

import logging
from typing import List

from app.config import settings
from app.run_settings import active_run_settings
from app.services.sources.base import NormalizedPost
from app.services.sources.research_utils import RESEARCH_BUZZ, text_links_to_paper
from app.services.sources.x_filters import filter_viral_posts
from app.services.x_api import XAPIError, x_api_service

logger = logging.getLogger(__name__)


class XResearchSource:
    name = "x_research"

    @property
    def is_configured(self) -> bool:
        return x_api_service.is_configured and settings.x_research_buzz_enabled

    async def search(self, query: str, max_results: int = 20) -> List[NormalizedPost]:
        if not self.is_configured:
            return []
        try:
            rs = active_run_settings()
            raw = await x_api_service.search_research_buzz(
                query,
                max_results=max_results,
                min_likes=rs.x_research_min_likes,
                min_impressions=rs.x_research_min_impressions,
            )
        except XAPIError as e:
            logger.warning(f"X research buzz search failed for '{query}': {e}")
            return []

        raw = [
            p for p in raw
            if text_links_to_paper(p.get("text", ""))
        ]
        raw = filter_viral_posts(
            raw,
            min_likes=rs.x_research_min_likes,
            min_impressions=rs.x_research_min_impressions,
        )

        posts: List[NormalizedPost] = []
        for p in raw:
            posts.append(
                {
                    "id": f"x-research-{p.get('id', '')}",
                    "source": self.name,
                    "content_type": RESEARCH_BUZZ,
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


x_research_source = XResearchSource()
