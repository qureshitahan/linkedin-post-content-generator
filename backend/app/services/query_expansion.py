import json
import logging
import re
from typing import List, Optional

from app.config import settings
from app.run_settings import active_run_settings
from app.services.claude import claude_service
from app.services.objective_parser import ParsedObjective

logger = logging.getLogger(__name__)


class QueryExpansionService:
    """Expand a content objective into specific search queries for all sources
    (Reddit, Hacker News, X) — short full-text phrases, not platform operators."""

    @property
    def is_configured(self) -> bool:
        return claude_service.is_configured

    def _fallback_queries(self, objective: str) -> List[str]:
        """Generate basic queries when Claude is unavailable."""
        base = objective.lower()
        words = re.findall(r"\b[a-z]{3,}\b", base)
        key_terms = [
            w
            for w in words
            if w not in {"about", "want", "write", "posts", "linkedin", "the", "and", "for"}
        ][:5]

        queries = []
        if key_terms:
            queries.append(" ".join(key_terms[:3]))
            for term in key_terms:
                queries.append(term)
                queries.append(f"{term} trending")
                queries.append(f"{term} debate")

        return queries[: active_run_settings().max_search_queries]

    async def expand_objective(
        self,
        parsed: ParsedObjective,
        trend_hints: Optional[List[str]] = None,
    ) -> List[str]:
        if not self.is_configured:
            logger.warning("Anthropic not configured, using fallback query expansion")
            return self._fallback_queries(parsed.content_goal or parsed.raw_text)

        trend_context = ""
        if trend_hints:
            trend_context = f"\n\nOptional broad X trends for context (use sparingly, prefer specific queries):\n{json.dumps(trend_hints[:10])}"

        avoid_line = ""
        if parsed.avoid_topics:
            avoid_line = f"\nAvoid queries that mostly surface unrelated topics: {', '.join(parsed.avoid_topics)}"

        prompt = f"""You are a content intelligence analyst. Generate search queries to find trending conversations and research across news, arXiv, PubMed, preprints, Hacker News, and X that this person could turn into LinkedIn posts.

{parsed.prompt_block()}

Generate {active_run_settings().max_search_queries} specific full-text search queries (2-5 words each).

Rules:
- Queries must reflect the CONTENT GOAL and FOCUS AREAS — any industry is valid
- Prefer specific sub-topics, tools, debates, launches, or workflows inside the user's goal
- These run as full-text search on forums — use natural phrases, NO operators/hashtags/quotes
- Avoid overly broad single-word queries ("AI", "health", "data" alone)
- Avoid ambiguous terms that pull unrelated domains (e.g. "data validation" alone surfaces crypto)
- Prefer compound phrases that disambiguate the domain ("marketing data pipeline", not "data pipeline")
- Include 2-3 queries aimed at research (papers, clinical trials, ML methods) when the goal involves science, healthcare, or data{avoid_line}
- Return ONLY a JSON array of strings
{trend_context}

Examples (adapt to the user's actual goal — do not copy these literally):
- Goal "AI in healthcare diagnostics": ["AI radiology FDA", "clinical AI workflow", "diagnostic AI debate"]
- Goal "startup fundraising": ["Series A climate tech", "VC AI agents", "founder fundraising tips"]
- Goal "media measurement analytics": ["brand lift study", "marketing mix modeling", "attribution measurement"]
"""

        try:
            content = claude_service.complete(
                prompt=prompt,
                system="You output only valid JSON arrays of search query strings for any domain.",
                model=settings.anthropic_model_fast,
                max_tokens=1024,
            )

            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\n?", "", content)
                content = re.sub(r"\n?```$", "", content)

            queries = json.loads(content)
            if isinstance(queries, list) and all(isinstance(q, str) for q in queries):
                return queries[: active_run_settings().max_search_queries]
        except Exception as e:
            logger.error(f"Query expansion failed: {e}")

        return self._fallback_queries(parsed.content_goal or parsed.raw_text)


query_expansion_service = QueryExpansionService()
