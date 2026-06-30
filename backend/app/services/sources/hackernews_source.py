"""Hacker News source via the free Algolia search API (no key, no auth).

Great for the data-engineering / AI-automation / developer-tooling side of a
professional profile. Endpoint docs: https://hn.algolia.com/api
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import List

import httpx

from app.services.sources.base import NormalizedPost

logger = logging.getLogger(__name__)

HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search"


class HackerNewsSource:
    name = "hackernews"

    @property
    def is_configured(self) -> bool:
        # No credentials required.
        return True

    async def search(self, query: str, max_results: int = 20) -> List[NormalizedPost]:
        since = int(
            (datetime.now(timezone.utc) - timedelta(days=7)).timestamp()
        )
        params = {
            "query": query,
            "tags": "story",
            "numericFilters": f"created_at_i>{since}",
            "hitsPerPage": max(10, min(max_results, 50)),
        }

        try:
            async with httpx.AsyncClient(timeout=20.0, trust_env=False) as client:
                resp = await client.get(HN_SEARCH_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            logger.warning(f"Hacker News search failed for '{query}': {e}")
            return []

        posts: List[NormalizedPost] = []
        for hit in data.get("hits", []):
            object_id = hit.get("objectID")
            if not object_id:
                continue

            title = hit.get("title") or hit.get("story_title") or ""
            body = hit.get("story_text") or ""
            text = title if not body else f"{title}\n\n{body}"
            text = _strip_html(text)

            created_iso = None
            created_i = hit.get("created_at_i")
            if created_i:
                created_iso = datetime.fromtimestamp(
                    created_i, tz=timezone.utc
                ).strftime("%Y-%m-%dT%H:%M:%SZ")

            author = hit.get("author", "unknown")
            comments = int(hit.get("num_comments") or 0)
            points = int(hit.get("points") or 0)

            posts.append(
                {
                    "id": f"hn-{object_id}",
                    "source": self.name,
                    "text": text,
                    "title": title,
                    "created_at": created_iso,
                    "author_name": author,
                    "author_handle": author,
                    "post_url": f"https://news.ycombinator.com/item?id={object_id}",
                    "likes": points,
                    "retweets": 0,
                    "replies": comments,
                    "comments": comments,
                    "impressions": None,
                }
            )

        return posts


def _strip_html(text: str) -> str:
    import re

    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&#x27;", "'").replace("&quot;", '"').replace("&amp;", "&")
    text = re.sub(r"\s+", " ", text).strip()
    return text


hackernews_source = HackerNewsSource()
