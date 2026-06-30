"""Industry RSS source — curated publications across healthcare, AI/ML, data
analytics, and tech news.

More focused than general Google News: these are publications practitioners
actually read, so the signal is higher and the links are citable. Feeds are
full-article lists (not query-able), so we fetch recent items once per run
and let the pipeline's relevance gate keep only on-topic ones.

Feeds are configurable via RSS_FEEDS in .env. Off-domain goals simply won't
pass the relevance filter, so a broad feed list is safe.
"""

import asyncio
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

import httpx

from app.config import settings
from app.services.sources.base import NormalizedPost

logger = logging.getLogger(__name__)

# Trade pubs are editorially curated, so treat each item as a moderate,
# uniform engagement signal (same idea as the news source).
RSS_ENGAGEMENT_PROXY = 45
_CACHE_TTL_SECONDS = 600
_ATOM_LINK = "{http://www.w3.org/2005/Atom}link"
_ATOM_ENTRY = "{http://www.w3.org/2005/Atom}entry"


class RSSSource:
    name = "industry"

    def __init__(self):
        # url -> (fetched_at, items)
        self._cache: Dict[str, Tuple[float, List[NormalizedPost]]] = {}

    @property
    def feeds(self) -> List[str]:
        return settings.rss_feed_list

    @property
    def is_configured(self) -> bool:
        return bool(self.feeds)

    async def search(self, query: str, max_results: int = 20) -> List[NormalizedPost]:
        """Query is ignored: RSS feeds aren't searchable. Return recent items
        from all feeds; the pipeline relevance-filters them."""
        feeds = self.feeds
        if not feeds:
            return []

        results = await asyncio.gather(
            *[self._fetch_feed(url) for url in feeds], return_exceptions=True
        )

        posts: List[NormalizedPost] = []
        seen = set()
        for res in results:
            if isinstance(res, Exception):
                continue
            for post in res:
                if post["id"] in seen:
                    continue
                seen.add(post["id"])
                posts.append(post)
        return posts

    async def _fetch_feed(self, url: str) -> List[NormalizedPost]:
        cached = self._cache.get(url)
        if cached and (time.time() - cached[0]) < _CACHE_TTL_SECONDS:
            return cached[1]

        try:
            async with httpx.AsyncClient(timeout=20.0, trust_env=False, follow_redirects=True) as client:
                resp = await client.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; ContentIntel/1.0)"},
                )
                resp.raise_for_status()
                root = ET.fromstring(resp.content)
        except (httpx.HTTPError, ET.ParseError) as e:
            logger.warning(f"RSS fetch failed for '{url}': {e}")
            self._cache[url] = (time.time(), [])
            return []

        items = self._parse(root, url)
        self._cache[url] = (time.time(), items)
        return items

    def _parse(self, root, feed_url: str) -> List[NormalizedPost]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=settings.rss_days_window)
        publisher = self._feed_title(root, feed_url)
        posts: List[NormalizedPost] = []

        # RSS 2.0 <item> and Atom <entry>
        nodes = root.findall(".//item") or root.findall(f".//{_ATOM_ENTRY}")
        for node in nodes:
            title = (self._text(node, "title")).strip()
            link = self._link(node)
            if not title or not link:
                continue

            created_dt = self._date(node)
            if created_dt and created_dt < cutoff:
                continue
            created_iso = (
                created_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                if created_dt
                else None
            )

            summary = _strip_html(
                self._text(node, "description") or self._text(node, "summary")
            )
            text = title if not summary else f"{title}. {summary[:280]}"

            posts.append(
                {
                    "id": f"rss-{abs(hash(link)) % (10**12)}",
                    "source": self.name,
                    "text": text,
                    "title": title,
                    "created_at": created_iso,
                    "author_name": publisher,
                    "author_handle": publisher,
                    "post_url": link,
                    "likes": 0,
                    "retweets": 0,
                    "replies": 0,
                    "comments": 0,
                    "engagement_proxy": RSS_ENGAGEMENT_PROXY,
                    "impressions": None,
                }
            )
        return posts

    def _feed_title(self, root, feed_url: str) -> str:
        channel = root.find("channel")
        if channel is not None:
            title = channel.findtext("title")
            if title:
                return title.strip()
        atom_title = root.findtext("{http://www.w3.org/2005/Atom}title")
        if atom_title:
            return atom_title.strip()
        # Fall back to the domain name
        m = re.search(r"https?://(?:www\.)?([^/]+)", feed_url)
        return m.group(1) if m else "Industry"

    def _text(self, node, tag: str) -> str:
        val = node.findtext(tag)
        if val:
            return val
        val = node.findtext(f"{{http://www.w3.org/2005/Atom}}{tag}")
        return val or ""

    def _link(self, node) -> str:
        # RSS 2.0
        link = node.findtext("link")
        if link and link.strip():
            return link.strip()
        # Atom <link href="...">
        for el in node.findall(_ATOM_LINK):
            rel = el.get("rel", "alternate")
            if rel == "alternate" and el.get("href"):
                return el.get("href").strip()
        first = node.find(_ATOM_LINK)
        return first.get("href", "").strip() if first is not None else ""

    def _date(self, node) -> Optional[datetime]:
        raw = node.findtext("pubDate")
        if raw:
            try:
                dt = parsedate_to_datetime(raw)
                return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
            except (TypeError, ValueError):
                pass
        iso = self._text(node, "updated") or self._text(node, "published")
        if iso:
            try:
                dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
                return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
            except ValueError:
                pass
        return None


def _strip_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&#8217;", "'").replace("&#8220;", '"').replace("&#8221;", '"')
    text = text.replace("&amp;", "&").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text).strip()


rss_source = RSSSource()
