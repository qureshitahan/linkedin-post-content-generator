"""Runs every enabled + configured source and returns a normalized post pool.

The pipeline calls this instead of talking to any single platform. New sources
can be added by registering them here.
"""

import asyncio
import logging
from typing import Dict, List, Optional

from app.config import settings
from app.run_settings import active_run_settings
from app.services.sources.base import NormalizedPost
from app.services.sources.arxiv_source import arxiv_source
from app.services.sources.devto_source import devto_source
from app.services.sources.hackernews_source import hackernews_source
from app.services.sources.news_source import news_source
from app.services.sources.preprint_source import preprint_source
from app.services.sources.pubmed_source import pubmed_source
from app.services.sources.reddit_source import reddit_source
from app.services.sources.rss_source import rss_source
from app.services.sources.x_research_source import x_research_source
from app.services.sources.x_source import x_source

logger = logging.getLogger(__name__)


class SourceAggregator:
    def __init__(self):
        self._registry = {
            "news": news_source,
            "industry": rss_source,
            "reddit": reddit_source,
            "hackernews": hackernews_source,
            "arxiv": arxiv_source,
            "pubmed": pubmed_source,
            "preprint": preprint_source,
            "devto": devto_source,
            "x_research": x_research_source,
            "x": x_source,
        }

    def _enabled_names(self) -> List[str]:
        rs = active_run_settings()
        configured = rs.enabled_sources or settings.enabled_source_list
        return [n for n in configured if n in self._registry]

    def active_sources(self) -> List[str]:
        """Names of sources enabled for this run and having valid credentials."""
        return [
            name
            for name in self._enabled_names()
            if self._registry[name].is_configured
        ]

    async def gather(
        self,
        queries: List[str],
        subreddits: Optional[List[str]] = None,
        per_query: Optional[int] = None,
    ) -> Dict:
        rs = active_run_settings()
        per_query = per_query or rs.posts_per_query
        active = self.active_sources()
        if not active:
            logger.warning("No active content sources configured")
            return {"posts": [], "by_query": {}, "by_source": {}, "active_sources": []}

        max_queries = rs.max_queries_per_source
        queries = queries[:max_queries]

        tasks = []
        meta = []

        query_agnostic = {"industry", "devto"}

        for name in active:
            source = self._registry[name]
            source_per_query = rs.posts_for_source(name)
            if name in query_agnostic:
                tasks.append(
                    source.search(queries[0] if queries else "", max_results=source_per_query)
                )
                meta.append((queries[0] if queries else "", name))
                continue
            source_queries = queries
            if name == "x_research":
                source_queries = queries[: rs.x_research_max_queries]
            for q in source_queries:
                tasks.append(source.search(q, max_results=source_per_query))
                meta.append((q, name))

        # Reddit: also search the goal-relevant subreddits directly (higher signal)
        if "reddit" in active and subreddits:
            primary_query = queries[0] if queries else ""
            for sub in subreddits[: settings.reddit_max_subreddits]:
                tasks.append(
                    reddit_source.search_subreddit(
                        primary_query, subreddit=sub, max_results=15
                    )
                )
                meta.append((primary_query, "reddit"))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        by_query: Dict[str, int] = {}
        by_source: Dict[str, int] = {}
        seen_ids = set()
        seen_text = set()
        posts: List[NormalizedPost] = []

        for (query, source_name), result in zip(meta, results):
            if isinstance(result, Exception):
                logger.warning(f"Source '{source_name}' failed for '{query}': {result}")
                continue
            for post in result:
                pid = post.get("id")
                text_key = (post.get("text", "")[:120]).strip().lower()
                if pid in seen_ids or (text_key and text_key in seen_text):
                    continue
                seen_ids.add(pid)
                if text_key:
                    seen_text.add(text_key)
                post["_query"] = query
                posts.append(post)
                by_query[query] = by_query.get(query, 0) + 1
                by_source[source_name] = by_source.get(source_name, 0) + 1

        return {
            "posts": posts,
            "by_query": by_query,
            "by_source": by_source,
            "active_sources": active,
        }


source_aggregator = SourceAggregator()
