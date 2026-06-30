"""Pluggable content sources for trend discovery.

Each source returns posts in a normalized shape so the rest of the
pipeline (relevance scoring, clustering, analysis) is source-agnostic.
"""

from app.services.sources.aggregator import source_aggregator
from app.services.sources.base import NormalizedPost, Source

__all__ = ["source_aggregator", "NormalizedPost", "Source"]
