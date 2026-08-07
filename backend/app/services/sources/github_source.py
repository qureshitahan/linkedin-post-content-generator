"""GitHub trending AI-tools source via the public Search API (token optional).

Surfaces actively-maintained, popular AI tool repositories (agents, LLM frameworks,
RAG, dev tools) so the pipeline can turn "here's a notable AI tool" into a LinkedIn
post that positions the author as an AI leader. The repo URL becomes the post's
reference link.

Query-agnostic (like the industry/devto sources): it fetches across the configured
AI-tool search terms rather than the per-topic query, so it reliably surfaces tools.
No key required; set GITHUB_TOKEN to raise the rate limit (10 -> 30 req/min).
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import httpx

from app.config import settings
from app.services.sources.base import NormalizedPost

logger = logging.getLogger(__name__)

GITHUB_SEARCH = "https://api.github.com/search/repositories"


class GitHubSource:
    name = "github"

    @property
    def is_configured(self) -> bool:
        return bool((settings.github_search_terms or "").strip())

    def _headers(self) -> dict:
        headers = {
            "User-Agent": "ContentIntel/1.0",
            "Accept": "application/vnd.github+json",
        }
        if settings.github_token:
            headers["Authorization"] = f"Bearer {settings.github_token}"
        return headers

    async def search(self, query: str, max_results: int = 20) -> List[NormalizedPost]:
        terms = [t.strip() for t in (settings.github_search_terms or "").split(",") if t.strip()]
        if not terms:
            return []
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=settings.github_days_window)
        ).strftime("%Y-%m-%d")

        results = await asyncio.gather(
            *[self._fetch_term(term, cutoff, max_results) for term in terms[:6]],
            return_exceptions=True,
        )

        posts: List[NormalizedPost] = []
        seen: set[str] = set()
        for res in results:
            if isinstance(res, Exception):
                logger.warning(f"GitHub search failed: {res}")
                continue
            for post in res:
                if post["id"] in seen:
                    continue
                seen.add(post["id"])
                posts.append(post)

        # Most-starred first — the biggest, most post-worthy tools lead.
        posts.sort(key=lambda p: p.get("likes", 0), reverse=True)
        return posts[:max_results]

    async def _fetch_term(self, term: str, cutoff: str, max_results: int) -> List[NormalizedPost]:
        params = {
            "q": f"{term} pushed:>{cutoff} stars:>={settings.github_min_stars}",
            "sort": "stars",
            "order": "desc",
            "per_page": min(max_results, 15),
        }
        try:
            async with httpx.AsyncClient(timeout=20.0, trust_env=False) as client:
                resp = await client.get(GITHUB_SEARCH, params=params, headers=self._headers())
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            logger.warning(f"GitHub search failed for '{term}': {e}")
            return []

        posts: List[NormalizedPost] = []
        for repo in data.get("items", []):
            post = self._normalize(repo)
            if post:
                posts.append(post)
        return posts

    def _normalize(self, repo: dict) -> Optional[NormalizedPost]:
        repo_id = repo.get("id")
        full_name = (repo.get("full_name") or "").strip()
        url = (repo.get("html_url") or "").strip()
        if not repo_id or not full_name or not url:
            return None

        description = (repo.get("description") or "").strip()
        stars = int(repo.get("stargazers_count") or 0)
        topics = ", ".join((repo.get("topics") or [])[:6])
        text = f"{full_name} ({stars:,} stars): {description}"
        if topics:
            text += f" Topics: {topics}."

        owner = repo.get("owner") or {}
        return {
            "id": f"github-{repo_id}",
            "source": self.name,
            "content_type": "tool",
            "text": text,
            "title": full_name,
            "created_at": repo.get("pushed_at") or repo.get("updated_at") or repo.get("created_at"),
            "author_name": owner.get("login") or "GitHub",
            "author_handle": owner.get("login") or "github",
            "post_url": url,
            "likes": stars,
            "retweets": int(repo.get("forks_count") or 0),
            "replies": int(repo.get("open_issues_count") or 0),
            "comments": int(repo.get("open_issues_count") or 0),
            "impressions": None,
        }


github_source = GitHubSource()
