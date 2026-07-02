import json
import logging
import re
from typing import List, Optional

from app.config import settings
from app.run_settings import active_run_settings
from app.services.claude import claude_service
from app.services.objective_parser import ParsedObjective, STOPWORDS

logger = logging.getLogger(__name__)


class QueryExpansionService:
    """Expand a content objective into specific search queries for all sources
    (Reddit, Hacker News, X) — short full-text phrases, not platform operators."""

    @property
    def is_configured(self) -> bool:
        return claude_service.is_configured

    def _topic_terms(self, text: str) -> List[str]:
        """Extract searchable topic terms, skipping meta/request words."""
        skip = STOPWORDS | {
            "according",
            "profile",
            "tell",
            "something",
            "create",
            "post",
            "educates",
            "their",
            "linkedin",
            "posts",
            "want",
            "help",
            "please",
            "based",
            "using",
        }
        words = re.findall(r"\b[a-z0-9]{3,}\b", text.lower())
        return [w for w in words if w not in skip]

    def _seed_queries_from_goal(self, parsed: ParsedObjective) -> List[str]:
        """Always include the user's literal goal phrasing — not just principle-derived terms."""
        seeds: List[str] = []
        goal = (parsed.content_goal or "").strip()
        raw = (parsed.raw_text or "").strip()

        for text in (goal, raw):
            cleaned = re.sub(r"\s+", " ", text).strip()
            if cleaned and len(cleaned) <= 120 and cleaned not in seeds:
                seeds.append(cleaned)

        for domain in (parsed.focus_domains or [])[:3]:
            if domain and domain not in seeds:
                seeds.append(domain)

        terms = self._topic_terms(goal or raw)
        if "agentic" in terms and "systems" in terms and "agentic systems" not in seeds:
            seeds.append("agentic AI systems")
        if "machine" in terms and "learning" in terms and "machine learning" not in seeds:
            seeds.append("machine learning AI")
        if len(terms) >= 2:
            phrase = " ".join(terms[:4])
            if phrase not in seeds:
                seeds.append(phrase)

        return seeds[:4]

    def _merge_queries(self, parsed: ParsedObjective, generated: List[str]) -> List[str]:
        seeds = self._seed_queries_from_goal(parsed)
        merged: List[str] = []
        for q in seeds + generated:
            q = q.strip()
            if q and q not in merged:
                merged.append(q)
        return merged[: active_run_settings().max_search_queries]

    def _fallback_queries(self, objective: str) -> List[str]:
        """Generate basic queries when Claude is unavailable."""
        terms = self._topic_terms(objective)
        queries: List[str] = []

        if "agentic" in terms:
            queries.extend(["agentic AI systems", "agentic AI architecture", "AI agents"])
        if "machine" in terms and "learning" in terms:
            queries.append("machine learning trends")
        if "ai" in terms:
            queries.append("AI agents enterprise")

        if len(terms) >= 2:
            queries.append(" ".join(terms[:3]))
            queries.append(" ".join(terms[:4]))

        for term in terms[:4]:
            if len(term) >= 5:
                queries.append(term)

        deduped: List[str] = []
        for q in queries:
            q = q.strip()
            if q and q not in deduped and len(q) >= 4:
                deduped.append(q)

        return deduped[: active_run_settings().max_search_queries]

    async def expand_objective(
        self,
        parsed: ParsedObjective,
        trend_hints: Optional[List[str]] = None,
    ) -> List[str]:
        if not self.is_configured:
            logger.warning("Anthropic not configured, using fallback query expansion")
            return self._merge_queries(
                parsed, self._fallback_queries(parsed.content_goal or parsed.raw_text)
            )

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
- Queries must reflect the CONTENT GOAL first — principle/resume background is for draft angle only, NOT for choosing unrelated search topics
- Always include queries using the user's exact goal language (e.g. if they said "media marketing", include "media marketing" and close variants)
- Prefer specific sub-topics, tools, debates, launches, or workflows inside the user's goal
- These run as full-text search on forums — use natural phrases, NO operators/hashtags/quotes
- Avoid overly broad single-word queries ("AI", "health", "data" alone)
- Avoid ambiguous terms that pull unrelated domains (e.g. "data validation" alone surfaces crypto)
- Prefer compound phrases that disambiguate the domain ("media marketing trends", not "data pipeline")
- Include 2-3 queries aimed at research (papers, clinical trials, ML methods) when the goal involves science, healthcare, or data{avoid_line}
- Return ONLY a JSON array of strings
{trend_context}

Examples (adapt to the user's actual goal — do not copy these literally):
- Goal "AI in healthcare diagnostics": ["AI radiology FDA", "clinical AI workflow", "diagnostic AI debate"]
- Goal "startup fundraising": ["Series A climate tech", "VC AI agents", "founder fundraising tips"]
- Goal "media marketing": ["media marketing trends", "retail media networks", "programmatic advertising debate"]
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
                return self._merge_queries(parsed, queries)
        except Exception as e:
            logger.error(f"Query expansion failed: {e}")

        return self._merge_queries(
            parsed, self._fallback_queries(parsed.content_goal or parsed.raw_text)
        )


query_expansion_service = QueryExpansionService()
