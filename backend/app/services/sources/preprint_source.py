"""bioRxiv / medRxiv source via the free biorxiv.org API (no key).

Healthcare and life-sciences preprints — especially valuable before peer review.
All items are tagged content_type=research_paper.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import httpx

from app.config import settings
from app.services.sources.base import NormalizedPost
from app.services.sources.research_utils import (
    RESEARCH_ENGAGEMENT_PROXY,
    RESEARCH_PAPER,
    author_label,
    matches_query,
    paper_text,
)

logger = logging.getLogger(__name__)

BIORXIV_API = "https://api.biorxiv.org/details"
_CACHE_TTL = 600


class PreprintSource:
    name = "preprint"

    def __init__(self):
        self._cache: Dict[str, Tuple[float, List[NormalizedPost]]] = {}

    @property
    def servers(self) -> List[str]:
        return settings.preprint_server_list

    @property
    def is_configured(self) -> bool:
        return bool(self.servers)

    async def search(self, query: str, max_results: int = 20) -> List[NormalizedPost]:
        servers = self.servers
        if not servers:
            return []

        results = await asyncio.gather(
            *[self._fetch_server(server) for server in servers],
            return_exceptions=True,
        )

        posts: List[NormalizedPost] = []
        seen = set()
        for res in results:
            if isinstance(res, Exception):
                continue
            for post in res:
                if not matches_query(post.get("text", ""), query):
                    continue
                pid = post["id"]
                if pid in seen:
                    continue
                seen.add(pid)
                posts.append(post)

        posts.sort(key=lambda p: p.get("created_at") or "", reverse=True)
        return posts[:max_results]

    async def _fetch_server(self, server: str) -> List[NormalizedPost]:
        cache_key = server
        cached = self._cache.get(cache_key)
        if cached and (time.time() - cached[0]) < _CACHE_TTL:
            return cached[1]

        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=settings.preprint_days_window)
        interval = f"{start.isoformat()}/{end.isoformat()}"

        posts: List[NormalizedPost] = []
        cursor = 0
        try:
            async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
                while cursor is not None and len(posts) < 200:
                    url = f"{BIORXIV_API}/{server}/{interval}/{cursor}/json"
                    resp = await client.get(
                        url,
                        headers={"User-Agent": "Mozilla/5.0 (compatible; ContentIntel/1.0)"},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    batch = data.get("collection") or []
                    for item in batch:
                        post = self._normalize(item, server)
                        if post:
                            posts.append(post)
                    messages = data.get("messages") or [{}]
                    total = int(messages[0].get("total") or 0)
                    cursor += len(batch)
                    if cursor >= total or not batch:
                        break
        except httpx.HTTPError as e:
            logger.warning(f"Preprint fetch failed for '{server}': {e}")
            self._cache[cache_key] = (time.time(), [])
            return []

        self._cache[cache_key] = (time.time(), posts)
        return posts

    def _normalize(self, item: dict, server: str) -> Optional[NormalizedPost]:
        title = (item.get("title") or "").strip()
        doi = (item.get("doi") or "").strip()
        if not title or not doi:
            return None

        abstract = (item.get("abstract") or "").strip()
        authors = (item.get("authors") or "").strip()
        date_str = (item.get("date") or "").strip()
        created_iso = None
        if date_str:
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                created_iso = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                pass

        domain = "medrxiv.org" if server == "medrxiv" else "biorxiv.org"
        url = f"https://www.{domain}/content/{doi}v{item.get('version', '1')}"

        return {
            "id": f"preprint-{server}-{doi.replace('/', '-')}",
            "source": self.name,
            "content_type": RESEARCH_PAPER,
            "text": paper_text(title, abstract),
            "title": title,
            "created_at": created_iso,
            "author_name": author_label(authors.replace(",", ";")),
            "author_handle": server,
            "post_url": url,
            "likes": 0,
            "retweets": 0,
            "replies": 0,
            "comments": 0,
            "engagement_proxy": RESEARCH_ENGAGEMENT_PROXY,
            "impressions": None,
        }


preprint_source = PreprintSource()
