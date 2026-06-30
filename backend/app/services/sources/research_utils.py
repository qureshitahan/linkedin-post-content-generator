"""Shared helpers for research-paper sources."""

import re
from typing import List, Optional

RESEARCH_PAPER = "research_paper"
RESEARCH_BUZZ = "research_buzz"

RESEARCH_ENGAGEMENT_PROXY = 35


def matches_query(text: str, query: str) -> bool:
    """True if any meaningful query term appears in text."""
    if not query.strip():
        return True
    hay = text.lower()
    terms = [t for t in re.findall(r"\b[a-z0-9]{3,}\b", query.lower()) if t not in _STOP]
    if not terms:
        return True
    return any(t in hay for t in terms)


_STOP = {
    "the", "and", "for", "with", "from", "about", "into", "that", "this",
    "are", "was", "were", "has", "have", "our", "new", "how", "what",
}


def author_label(authors: str, max_names: int = 3) -> str:
    if not authors:
        return "Research"
    parts = [a.strip() for a in authors.split(";") if a.strip()]
    if len(parts) <= max_names:
        return ", ".join(parts)
    return ", ".join(parts[:max_names]) + " et al."


def paper_text(title: str, summary: Optional[str], max_summary: int = 240) -> str:
    title = (title or "").strip()
    summary = (summary or "").strip()
    if not summary:
        return title
    return f"{title}. {summary[:max_summary]}"
