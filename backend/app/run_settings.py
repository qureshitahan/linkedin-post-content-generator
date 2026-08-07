"""Per-run settings for discovery — overrides .env defaults when the user clicks Analyze."""

from __future__ import annotations

import json
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import List, Optional

from app.config import settings

# Thread/async-safe override for the duration of one pipeline run.
_current: ContextVar[Optional["RunSettings"]] = ContextVar("run_settings", default=None)

ALL_SOURCES = (
    "news",
    "industry",
    "hackernews",
    "arxiv",
    "pubmed",
    "preprint",
    "devto",
    "github",
    "x_research",
    "x",
)

DRAFT_STYLE_OPTIONS = (
    ("provocative", "Bold hook", "Sharp, scroll-stopping opener. Contrarian or surprising."),
    ("analytical", "Evidence-led", "Lead with a finding, stat, or concrete fact from the evidence."),
    ("story", "Personal POV", "Practitioner voice. One real insight from experience."),
    ("curious", "Question-led", "Open with a specific question practitioners debate."),
    ("actionable", "Practical takeaway", "Focus on what to do differently. Clear, useful."),
)


@dataclass
class RunSettings:
    enabled_sources: List[str] = field(default_factory=list)
    max_queries_per_source: int = 5
    posts_per_query: int = 15
    max_topics_to_analyze: int = 3
    max_search_queries: int = 6
    # X / Twitter (paid API)
    x_posts_per_query: int = 10
    x_min_likes: int = 0
    x_min_impressions: int = 0
    x_research_min_likes: int = 30
    x_research_min_impressions: int = 0
    x_research_max_queries: int = 2
    # Draft styles — used when user clicks "Generate drafts" on a topic (not during discovery)
    draft_styles: List[str] = field(
        default_factory=lambda: [s[0] for s in DRAFT_STYLE_OPTIONS]
    )

    @classmethod
    def from_env(cls) -> "RunSettings":
        return cls(
            enabled_sources=list(settings.enabled_source_list),
            max_queries_per_source=settings.max_queries_per_source,
            posts_per_query=settings.posts_per_query,
            max_topics_to_analyze=settings.max_topics_to_analyze,
            max_search_queries=settings.max_search_queries,
            x_posts_per_query=min(15, settings.posts_per_query),
            x_min_likes=0,
            x_min_impressions=0,
            x_research_min_likes=settings.x_research_min_likes,
            x_research_min_impressions=0,
            x_research_max_queries=settings.x_research_max_queries,
        )

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "RunSettings":
        base = cls.from_env()
        if not data:
            return base
        for key, val in data.items():
            if hasattr(base, key) and val is not None:
                setattr(base, key, val)
        return base

    def to_dict(self) -> dict:
        return {
            "enabled_sources": self.enabled_sources,
            "max_queries_per_source": self.max_queries_per_source,
            "posts_per_query": self.posts_per_query,
            "max_topics_to_analyze": self.max_topics_to_analyze,
            "max_search_queries": self.max_search_queries,
            "x_posts_per_query": self.x_posts_per_query,
            "x_min_likes": self.x_min_likes,
            "x_min_impressions": self.x_min_impressions,
            "x_research_min_likes": self.x_research_min_likes,
            "x_research_min_impressions": self.x_research_min_impressions,
            "x_research_max_queries": self.x_research_max_queries,
            "draft_styles": self.draft_styles,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, raw: Optional[str]) -> "RunSettings":
        if not raw:
            return cls.from_env()
        try:
            return cls.from_dict(json.loads(raw))
        except json.JSONDecodeError:
            return cls.from_env()

    def posts_for_source(self, source_name: str) -> int:
        if source_name in ("x", "x_research"):
            return self.x_posts_per_query
        return self.posts_per_query

    def is_source_enabled(self, name: str) -> bool:
        return name in self.enabled_sources


def active_run_settings() -> RunSettings:
    return _current.get() or RunSettings.from_env()


def run_settings_context(rs: RunSettings):
    """Context manager to apply per-run settings during pipeline execution."""
    token = _current.set(rs)
    try:
        yield rs
    finally:
        _current.reset(token)


class _RunSettingsContextManager:
    def __init__(self, rs: RunSettings):
        self.rs = rs
        self.token = None

    def __enter__(self):
        self.token = _current.set(self.rs)
        return self.rs

    def __exit__(self, *args):
        if self.token is not None:
            _current.reset(self.token)


def apply_run_settings(rs: RunSettings) -> _RunSettingsContextManager:
    return _RunSettingsContextManager(rs)
