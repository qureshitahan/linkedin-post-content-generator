"""Resolve redirect URLs (e.g. Google News RSS) to publisher article links."""

import asyncio
import logging
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

_REDIRECT_HOSTS = ("news.google.com", "google.com")
_USER_AGENT = "Mozilla/5.0 (compatible; LinkedInContentIntel/1.0)"


def is_redirect_wrapper(url: str) -> bool:
    if not url:
        return False
    host = urlparse(url).netloc.lower()
    return any(h in host for h in _REDIRECT_HOSTS) and (
        "/rss/articles/" in url or "/url?" in url
    )


def is_usable_reference_url(url: str) -> bool:
    """Whether a URL is safe to show as a draft/evidence reference."""
    if not url:
        return False
    if is_redirect_wrapper(url):
        return False
    host = urlparse(url).netloc.lower()
    if "news.google.com" in host:
        return False
    return True


async def resolve_article_url(url: str) -> str:
    """Follow redirects and return the final publisher URL when possible."""
    if not url or not is_redirect_wrapper(url):
        return url

    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            trust_env=False,
        ) as client:
            resp = await client.get(url, headers={"User-Agent": _USER_AGENT})
            final = str(resp.url)
            if final and is_usable_reference_url(final):
                return final
    except Exception as e:
        logger.warning("Could not resolve article URL %s: %s", url[:80], e)

    return url


async def resolve_post_urls(posts: list[dict]) -> None:
    """In-place: resolve Google News wrapper links on gathered posts."""
    tasks = []
    indices: list[int] = []
    for i, post in enumerate(posts):
        url = post.get("post_url") or ""
        if is_redirect_wrapper(url):
            tasks.append(resolve_article_url(url))
            indices.append(i)

    if not tasks:
        return

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for idx, result in zip(indices, results):
        if isinstance(result, str) and result and is_usable_reference_url(result):
            posts[idx]["post_url"] = result
