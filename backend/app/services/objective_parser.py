import json
import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

from app.config import settings
from app.services.claude import claude_service

logger = logging.getLogger(__name__)

GOAL_MARKERS = (
    r"---+\s*\n",
    r"\bgoal:\s*",
    r"and now i want",
    r"i want to write",
    r"i want linkedin",
    r"i want posts about",
    r"what can it be",
    r"my goal is",
    r"help me write",
)

STOPWORDS = frozenset(
    {
        "about",
        "want",
        "write",
        "posts",
        "linkedin",
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "what",
        "good",
        "stuff",
        "which",
        "have",
        "been",
        "would",
        "like",
        "make",
        "trending",
        "research",
        "deeply",
    }
)


@dataclass
class ParsedObjective:
    author_summary: str
    content_goal: str
    focus_domains: List[str] = field(default_factory=list)
    relevance_keywords: List[str] = field(default_factory=list)
    avoid_topics: List[str] = field(default_factory=list)
    proof_points: List[str] = field(default_factory=list)
    subreddits: List[str] = field(default_factory=list)
    raw_text: str = ""
    principle_name: str = ""
    principle_snippets: List[str] = field(default_factory=list)

    def prompt_block(self) -> str:
        focus = ", ".join(self.focus_domains) if self.focus_domains else "derived from the user's goal"
        relevance = ", ".join(self.relevance_keywords[:12]) if self.relevance_keywords else focus
        avoid = ", ".join(self.avoid_topics) if self.avoid_topics else "(none — stay aligned to the goal only)"
        proofs = "\n".join(f"- {p}" for p in self.proof_points[:5]) if self.proof_points else "- (none provided)"

        principle_block = ""
        if self.principle_name or self.principle_snippets:
            snippets = "\n".join(f"- {s}" for s in self.principle_snippets[:8]) or "- (no indexed documents yet)"
            principle_block = f"""
PRINCIPLE PROFILE ({self.principle_name or "selected author"}):
Indexed background from uploaded documents. When the topic connects naturally, weave in 0-2 relevant experiences, projects, or achievements from below. Do NOT force a personal link if it feels stretched. Readers engage more when posts connect trending topics to real credibility.

{snippets}
"""

        return f"""AUTHOR (who is writing the post):
{self.author_summary}

CONTENT GOAL (what they want posts about):
{self.content_goal}

FOCUS AREAS:
{focus}

SIGNALS OF A RELEVANT X POST (match the goal, not random keyword overlap):
{relevance}

TOPICS TO AVOID IN DRAFTS (tangential to the goal — do not center posts on these):
{avoid}

REAL EXPERIENCE TO GROUND THE DRAFT (use 0-2, do not invent):
{proofs}{principle_block}"""


class ObjectiveParserService:
    """Turn background + goal text into structured writer context for any domain."""

    @property
    def is_configured(self) -> bool:
        return claude_service.is_configured

    def _split_goal_from_context(self, text: str) -> tuple[str, str]:
        if "---" in text:
            parts = text.split("---", 1)
            background = parts[0].strip()
            goal = parts[1].strip()
            if goal:
                return background, re.sub(r"^goal:\s*", "", goal, flags=re.I)

        lower = text.lower()
        for marker in GOAL_MARKERS:
            match = re.search(marker, lower)
            if match:
                idx = match.start()
                background = text[:idx].strip()
                goal = text[idx:].strip()
                goal = re.sub(r"^goal:\s*", "", goal, flags=re.I)
                return background, goal

        trimmed = text.strip()
        if len(trimmed) > 800:
            return trimmed, "Write LinkedIn posts about trends that match my background and interests."
        return "", trimmed

    def _extract_keywords(self, *texts: str, limit: int = 12) -> List[str]:
        combined = " ".join(t for t in texts if t).lower()
        phrases = re.findall(r"[a-z][a-z0-9+\-/ ]{2,40}[a-z0-9]", combined)
        keywords: List[str] = []

        for phrase in sorted(set(phrases), key=len, reverse=True):
            cleaned = re.sub(r"\s+", " ", phrase.strip())
            if len(cleaned) < 4 or cleaned in STOPWORDS:
                continue
            if any(w in STOPWORDS for w in cleaned.split() if len(cleaned.split()) == 1):
                continue
            keywords.append(cleaned)
            if len(keywords) >= limit:
                break

        if not keywords:
            words = re.findall(r"\b[a-z]{4,}\b", combined)
            keywords = [w for w in dict.fromkeys(words) if w not in STOPWORDS][:limit]

        return keywords

    def _heuristic_parse(self, objective: str) -> ParsedObjective:
        background, goal = self._split_goal_from_context(objective)
        background_short = re.sub(r"\s+", " ", background)[:1200] if background else ""

        focus = self._extract_keywords(goal, limit=6)
        if not focus and background:
            focus = self._extract_keywords(background, limit=4)

        relevance = self._extract_keywords(goal, limit=12)
        if not relevance:
            relevance = focus.copy()

        proof_points = []
        for line in (background or objective).splitlines():
            stripped = line.strip()
            if stripped.startswith("•") or stripped.startswith("-"):
                proof_points.append(re.sub(r"^[•\-]\s*", "", stripped)[:220])
        proof_points = proof_points[:5]

        return ParsedObjective(
            author_summary=background_short or "Professional sharing insight in their field.",
            content_goal=goal or objective.strip(),
            focus_domains=focus[:6],
            relevance_keywords=relevance,
            avoid_topics=[],
            proof_points=proof_points,
            subreddits=[],
            raw_text=objective,
        )

    async def parse(
        self,
        objective: str,
        *,
        principle_background: str = "",
        principle_name: str = "",
    ) -> ParsedObjective:
        if not self.is_configured:
            parsed = self._heuristic_parse(objective)
            if principle_background:
                parsed.author_summary = (
                    f"{parsed.author_summary} Background from principle documents: "
                    f"{principle_background[:600]}"
                )
            parsed.principle_name = principle_name
            return parsed

        background, goal = self._split_goal_from_context(objective)
        principle_section = ""
        if principle_background.strip():
            principle_section = f"""
INDEXED PRINCIPLE DOCUMENTS (author background — use for author_summary and proof_points):
{principle_background[:12000]}
"""
        prompt = f"""Parse this input for a LinkedIn content tool. Works for ANY industry (healthcare, finance, dev tools, marketing, etc.).

PRINCIPLE / AUTHOR: {principle_name or "(not specified)"}

BACKGROUND (optional — resume, skills, context from the objective text):
{background[:8000] if background else "(none in objective — use principle documents if provided)"}
{principle_section}
WRITING GOAL:
{goal[:2000]}

Return JSON only:
{{
  "author_summary": "2-3 sentences: who they are and what they do. Prefer principle documents when provided.",
  "content_goal": "One clear sentence restating what LinkedIn posts they want",
  "focus_domains": ["3-6 broad areas from the GOAL — not random resume jobs unless the goal asks for them"],
  "relevance_keywords": ["8-15 words/phrases from the GOAL that signal a post is actually on-topic"],
  "avoid_topics": ["0-5 topics to avoid in drafts — only if background mentions areas unrelated to the goal, or the user explicitly excludes something. Empty array if nothing to avoid."],
  "proof_points": ["0-5 concrete achievements from principle documents or background that fit the GOAL — skip unrelated old roles"],
  "subreddits": ["3-8 ACTIVE, REAL subreddit names (no 'r/' prefix) where professionals discuss this goal. e.g. marketing analytics -> marketing, analytics, adops, PPC, dataengineering, datascience. Pick communities likely to contain on-topic discussion."]
}}

Rules:
- Derive everything from what the user WANTS to write about, not from every line of their resume
- When principle documents are provided, extract real achievements, companies, and skills from them
- If background includes unrelated past work (e.g. crypto job but goal is marketing analytics), put the unrelated area in avoid_topics
- If the user is a crypto founder wanting crypto posts, do NOT put crypto in avoid_topics
- relevance_keywords should help filter noise that only matches a search query literally but not the user's intent
- subreddits must be plausible real communities for the goal's profession/industry
- Be versatile — this parser must work for any profession and any goal"""

        try:
            content = claude_service.complete(
                prompt=prompt,
                system="You extract structured writer context for any domain. Output only valid JSON.",
                model=settings.anthropic_model_fast,
                max_tokens=1024,
                temperature=0.2,
            )
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\n?", "", content)
                content = re.sub(r"\n?```$", "", content)

            data = json.loads(content)
            parsed = ParsedObjective(
                author_summary=str(data.get("author_summary", "")).strip()
                or "Professional sharing insight in their field.",
                content_goal=str(data.get("content_goal", goal)).strip() or goal,
                focus_domains=[str(d).strip() for d in data.get("focus_domains", []) if d][:6],
                relevance_keywords=[str(k).strip() for k in data.get("relevance_keywords", []) if k][:15],
                avoid_topics=[str(a).strip() for a in data.get("avoid_topics", []) if a][:6],
                proof_points=[str(p).strip() for p in data.get("proof_points", []) if p][:5],
                subreddits=[
                    str(s).strip().lstrip("r/").strip("/")
                    for s in data.get("subreddits", [])
                    if s
                ][:8],
                raw_text=objective,
                principle_name=principle_name,
            )
            if not parsed.relevance_keywords:
                parsed.relevance_keywords = self._extract_keywords(parsed.content_goal, limit=12)
            return parsed
        except Exception as e:
            logger.error(f"Objective parsing failed: {e}")
            parsed = self._heuristic_parse(objective)
            parsed.principle_name = principle_name
            return parsed


def _keyword_in_text(keyword: str, text: str) -> bool:
    keyword = keyword.lower().strip()
    if not keyword:
        return False
    if " " in keyword:
        return keyword in text
    return re.search(rf"\b{re.escape(keyword)}\b", text) is not None


def score_post_relevance(
    post_text: str,
    parsed: ParsedObjective,
    query: str = "",
) -> float:
    """Score how well a post matches this user's stated goal (not a fixed industry list)."""
    text = post_text.lower()
    score = 0.0

    for domain in parsed.focus_domains:
        if _keyword_in_text(domain, text):
            score += 2.0

    for keyword in parsed.relevance_keywords:
        if _keyword_in_text(keyword, text):
            score += 1.0

    # Direct terms from the user's goal text (broader than LLM-parsed keywords alone)
    goal_terms = re.findall(r"\b[a-z]{4,}\b", (parsed.content_goal or "").lower())
    seen_goal: set[str] = set()
    for term in goal_terms:
        if term in STOPWORDS or term in seen_goal:
            continue
        seen_goal.add(term)
        if _keyword_in_text(term, text):
            score += 0.75

    # Posts returned for a query should get credit when the query terms appear in the headline
    if query:
        q_terms = [
            w for w in re.findall(r"\b[a-z]{3,}\b", query.lower()) if w not in STOPWORDS
        ]
        if q_terms:
            matches = sum(1 for t in q_terms if t in text)
            if matches >= max(1, len(q_terms) // 2):
                score += 1.5
            elif matches:
                score += matches * 0.5

    for topic in parsed.avoid_topics:
        if _keyword_in_text(topic, text):
            score -= 2.5

    return score


def filter_relevant_posts(posts: list[dict], parsed: ParsedObjective, min_keep: int = 3) -> list[dict]:
    """Prefer posts that match the user's goal; drop tangential noise when enough signal exists."""
    if not posts:
        return posts

    scored = [(score_post_relevance(p.get("text", ""), parsed, p.get("_query", "")), p) for p in posts]
    scored.sort(key=lambda x: x[0], reverse=True)

    if not parsed.relevance_keywords and not parsed.focus_domains:
        return [p for _, p in scored[:20]]

    relevant = [p for s, p in scored if s > 0]
    if len(relevant) >= min_keep:
        return relevant[:20]

    if parsed.avoid_topics:
        not_noise = [p for s, p in scored if s >= 0]
        if len(not_noise) >= min_keep:
            return not_noise[:20]

    return [p for _, p in scored[: max(min_keep, 8)]]


objective_parser_service = ObjectiveParserService()
