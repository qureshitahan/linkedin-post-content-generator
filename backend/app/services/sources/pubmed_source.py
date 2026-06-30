"""PubMed source via NCBI E-utilities (free, no API key).

Strong for peer-reviewed healthcare and clinical research. Returns papers
tagged as content_type=research_paper so the UI can filter them.
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from xml.etree import ElementTree as ET

import httpx

from app.config import settings
from app.services.sources.base import NormalizedPost
from app.services.sources.research_utils import (
    RESEARCH_ENGAGEMENT_PROXY,
    RESEARCH_PAPER,
    author_label,
    paper_text,
)

logger = logging.getLogger(__name__)

ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ContentIntel/1.0)"}


class PubmedSource:
    name = "pubmed"

    @property
    def is_configured(self) -> bool:
        return True

    async def search(self, query: str, max_results: int = 20) -> List[NormalizedPost]:
        if not query.strip():
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(days=settings.pubmed_days_window)
        date_filter = cutoff.strftime("%Y/%m/%d")

        try:
            async with httpx.AsyncClient(timeout=25.0, trust_env=False) as client:
                search_resp = await client.get(
                    ESEARCH,
                    params={
                        "db": "pubmed",
                        "term": f"({query}) AND ({date_filter}:3000[dp])",
                        "retmax": min(max_results, 30),
                        "sort": "date",
                        "retmode": "json",
                    },
                    headers=_HEADERS,
                )
                search_resp.raise_for_status()
                ids = search_resp.json().get("esearchresult", {}).get("idlist", [])
                if not ids:
                    return []

                fetch_resp = await client.get(
                    EFETCH,
                    params={"db": "pubmed", "id": ",".join(ids), "retmode": "xml"},
                    headers=_HEADERS,
                )
                fetch_resp.raise_for_status()
                root = ET.fromstring(fetch_resp.content)
        except (httpx.HTTPError, ET.ParseError) as e:
            logger.warning(f"PubMed search failed for '{query}': {e}")
            return []

        posts: List[NormalizedPost] = []
        for article in root.findall(".//PubmedArticle"):
            post = self._parse_article(article)
            if post:
                posts.append(post)
        return posts[:max_results]

    def _parse_article(self, article) -> Optional[NormalizedPost]:
        pmid_el = article.find(".//PMID")
        pmid = pmid_el.text.strip() if pmid_el is not None and pmid_el.text else ""
        if not pmid:
            return None

        title_el = article.find(".//ArticleTitle")
        title = _clean(title_el.text if title_el is not None else "")
        if not title:
            return None

        abstract_parts = []
        for abs_text in article.findall(".//AbstractText"):
            if abs_text.text:
                abstract_parts.append(abs_text.text.strip())
        summary = " ".join(abstract_parts)

        authors = []
        for author in article.findall(".//Author"):
            last = author.findtext("LastName", default="").strip()
            fore = author.findtext("ForeName", default="").strip()
            if last:
                authors.append(f"{fore} {last}".strip())

        journal = article.findtext(".//Journal/Title", default="PubMed").strip()
        doi = ""
        for aid in article.findall(".//ArticleId"):
            if aid.get("IdType") == "doi" and aid.text:
                doi = aid.text.strip()
                break

        pub_date = article.find(".//PubDate")
        created_iso = None
        if pub_date is not None:
            y = pub_date.findtext("Year")
            m = pub_date.findtext("Month", default="1")
            d = pub_date.findtext("Day", default="1")
            if y:
                try:
                    month_map = {
                        "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
                        "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
                    }
                    mi = month_map.get(m[:3], int(m) if str(m).isdigit() else 1)
                    di = int(d) if str(d).isdigit() else 1
                    dt = datetime(int(y), mi, di, tzinfo=timezone.utc)
                    created_iso = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                except (ValueError, TypeError):
                    pass

        url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        if doi:
            url = f"https://doi.org/{doi}"

        return {
            "id": f"pubmed-{pmid}",
            "source": self.name,
            "content_type": RESEARCH_PAPER,
            "text": paper_text(title, summary),
            "title": title,
            "created_at": created_iso,
            "author_name": author_label(", ".join(authors)) if authors else journal,
            "author_handle": journal,
            "post_url": url,
            "likes": 0,
            "retweets": 0,
            "replies": 0,
            "comments": 0,
            "engagement_proxy": RESEARCH_ENGAGEMENT_PROXY,
            "impressions": None,
        }


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


pubmed_source = PubmedSource()
