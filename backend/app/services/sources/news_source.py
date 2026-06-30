"""News source via Google News RSS (free, no key, no auth).

This is the strongest signal for "what's trending in <professional field>":
editorially curated articles from real publishers (AdAge, Digiday, TechCrunch,
BCG, etc.) with authoritative links you can cite in a LinkedIn post. Unlike X
recent-search, every item here already cleared an editorial bar, so you don't
get dead 2-impression tweets.
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import List, Optional
from xml.etree import ElementTree as ET

import httpx

from app.config import settings
from app.services.sources.base import NormalizedPost

logger = logging.getLogger(__name__)

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"

# News has no like/comment metrics. Treat editorial pickup as a moderate,
# uniform engagement signal so news competes on relevance + freshness.
NEWS_ENGAGEMENT_PROXY = 40


class NewsSource:
    name = "news"

    @property
    def is_configured(self) -> bool:
        return True

    async def search(self, query: str, max_results: int = 20) -> List[NormalizedPost]:
        params = {
            "q": query,
            "hl": "en-US",
            "gl": "US",
            "ceid": "US:en",
        }
        try:
            async with httpx.AsyncClient(timeout=20.0, trust_env=False) as client:
                resp = await client.get(
                    GOOGLE_NEWS_RSS,
                    params=params,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; ContentIntel/1.0)"},
                )
                resp.raise_for_status()
                root = ET.fromstring(resp.text)
        except (httpx.HTTPError, ET.ParseError) as e:
            logger.warning(f"Google News search failed for '{query}': {e}")
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(days=settings.news_days_window)
        posts: List[NormalizedPost] = []

        for item in root.findall(".//item")[: max_results * 2]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            if not title or not link:
                continue

            publisher = self._publisher(item)
            # Google News titles are "Headline - Publisher"; trim the suffix.
            headline = title
            if publisher and headline.endswith(f" - {publisher}"):
                headline = headline[: -(len(publisher) + 3)].strip()

            created_dt = self._parse_date(item.findtext("pubDate"))
            if created_dt and created_dt < cutoff:
                continue

            created_iso = (
                created_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                if created_dt
                else None
            )

            posts.append(
                {
                    "id": f"news-{abs(hash(link)) % (10**12)}",
                    "source": self.name,
                    "text": headline,
                    "title": headline,
                    "created_at": created_iso,
                    "author_name": publisher or "News",
                    "author_handle": publisher or "news",
                    "post_url": link,
                    "likes": 0,
                    "retweets": 0,
                    "replies": 0,
                    "comments": 0,
                    "engagement_proxy": NEWS_ENGAGEMENT_PROXY,
                    "impressions": None,
                }
            )
            if len(posts) >= max_results:
                break

        return posts

    def _publisher(self, item) -> str:
        for tag in ("source", "{*}source"):
            el = item.find(tag)
            if el is not None and (el.text or "").strip():
                return el.text.strip()
        return ""

    def _parse_date(self, value: Optional[str]):
        if not value:
            return None
        try:
            dt = parsedate_to_datetime(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (TypeError, ValueError):
            return None


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()


news_source = NewsSource()
