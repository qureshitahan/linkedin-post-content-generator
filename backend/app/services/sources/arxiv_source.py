"""arXiv source via the free Atom API (no key, no auth).

Surfaces recent AI/ML, statistics, and quantitative-biology papers — useful for
healthcare-AI and data-science objectives where research papers are citable
evidence. Categories are configurable via ARXIV_CATEGORIES in .env.
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from xml.etree import ElementTree as ET

import httpx

from app.config import settings
from app.services.sources.base import NormalizedPost

logger = logging.getLogger(__name__)

ARXIV_API = "https://export.arxiv.org/api/query"
_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"

# Research papers have no likes; treat publication as moderate editorial signal.
ARXIV_ENGAGEMENT_PROXY = 35


class ArxivSource:
    name = "arxiv"

    @property
    def is_configured(self) -> bool:
        return bool(settings.arxiv_category_list)

    async def search(self, query: str, max_results: int = 20) -> List[NormalizedPost]:
        """Search recent papers by keyword within configured categories."""
        cats = settings.arxiv_category_list
        if not cats:
            return []

        cat_filter = "+OR+".join(f"cat:{c}" for c in cats)
        search = f"({cat_filter})"
        if query.strip():
            # Quote multi-word queries; arXiv treats unquoted terms as AND.
            terms = query.strip().split()
            if len(terms) == 1:
                search += f"+AND+all:{terms[0]}"
            else:
                search += f"+AND+all:{query.strip()}"

        params = {
            "search_query": search,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "max_results": max(5, min(max_results, 50)),
        }

        try:
            async with httpx.AsyncClient(timeout=25.0, trust_env=False) as client:
                resp = await client.get(
                    ARXIV_API,
                    params=params,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; ContentIntel/1.0)"},
                )
                resp.raise_for_status()
                root = ET.fromstring(resp.content)
        except (httpx.HTTPError, ET.ParseError) as e:
            logger.warning(f"arXiv search failed for '{query}': {e}")
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(days=settings.arxiv_days_window)
        posts: List[NormalizedPost] = []

        for entry in root.findall(f"{_ATOM}entry"):
            title = _clean_text(entry.findtext(f"{_ATOM}title"))
            summary = _clean_text(entry.findtext(f"{_ATOM}summary"))
            if not title:
                continue

            link = ""
            for link_el in entry.findall(f"{_ATOM}link"):
                if link_el.get("rel", "alternate") == "alternate" and link_el.get("href"):
                    link = link_el.get("href", "").strip()
                    break
            if not link:
                link = (entry.findtext(f"{_ATOM}id") or "").strip()
            if not link:
                continue

            created_dt = _parse_date(entry.findtext(f"{_ATOM}published"))
            if created_dt and created_dt < cutoff:
                continue
            created_iso = (
                created_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                if created_dt
                else None
            )

            authors = [
                a.findtext(f"{_ATOM}name", default="").strip()
                for a in entry.findall(f"{_ATOM}author")
            ]
            author_str = ", ".join(a for a in authors[:3] if a)
            if len(authors) > 3:
                author_str += " et al."

            text = title
            if summary:
                text = f"{title}. {summary[:240]}"

            arxiv_id = link.rstrip("/").split("/")[-1]
            posts.append(
                {
                    "id": f"arxiv-{arxiv_id}",
                    "source": self.name,
                    "content_type": "research_paper",
                    "text": text,
                    "title": title,
                    "created_at": created_iso,
                    "author_name": author_str or "arXiv",
                    "author_handle": "arxiv",
                    "post_url": link,
                    "likes": 0,
                    "retweets": 0,
                    "replies": 0,
                    "comments": 0,
                    "engagement_proxy": ARXIV_ENGAGEMENT_PROXY,
                    "impressions": None,
                }
            )

        return posts


def _clean_text(text: Optional[str]) -> str:
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_date(value: Optional[str]):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except ValueError:
        return None


arxiv_source = ArxivSource()
