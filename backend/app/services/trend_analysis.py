import json
import logging
import re
from typing import List, Optional

from app.config import settings
from app.run_settings import DRAFT_STYLE_OPTIONS, active_run_settings
from app.services.claude import claude_service
from app.services.objective_parser import ParsedObjective, filter_relevant_posts
from app.services.sources.research_utils import RESEARCH_PAPER, text_links_to_paper
from app.services.url_utils import is_usable_reference_url

logger = logging.getLogger(__name__)

BANNED_DRAFT_PATTERNS = (
    "i've been watching",
    "here's what's actually happening",
    "the real question isn't whether",
    "what angle would you take",
    "six months ago",
    "ai is changing the world",
    "let that sink in",
    "hot take:",
    "unpopular opinion:",
    "in today's fast-paced",
    "game-changer",
    "game changer",
    "the bottom line",
    "at the end of the day",
    "delve into",
    "it's not just",
    "isn't just",
    "let's dive in",
    "dive deep",
)

# URLs we never want to surface as a "reference" (link shorteners / tracking)
_BAD_LINK_HOSTS = ("t.co", "bit.ly", "lnkd.in", "buff.ly", "ift.tt")
_URL_RE = re.compile(r"https?://[^\s)\]}'\"]+")

DRAFT_STYLES = DRAFT_STYLE_OPTIONS  # (style_key, label, description) — see run_settings.py


def _draft_styles_block(style_keys: Optional[list] = None) -> str:
    keys = style_keys or [s[0] for s in DRAFT_STYLES]
    lines = []
    for style_key, label, desc in DRAFT_STYLES:
        if style_key in keys:
            lines.append(f'- "{label}" (style: {style_key}): {desc}')
    return "\n".join(lines)


def _styles_from_keys(style_keys: list) -> list:
    """Map style keys to (label, style, desc) tuples."""
    by_key = {s[0]: s for s in DRAFT_STYLES}
    return [by_key[k] for k in style_keys if k in by_key]


def _normalize_drafts(raw_drafts: list, ref_url: str, fallback_text: str) -> list[dict]:
    """Ensure we have a valid list of draft dicts with label, style, text."""
    normalized = []
    for i, item in enumerate(raw_drafts):
        if isinstance(item, dict) and item.get("text"):
            text = _finalize_draft_static(item["text"], ref_url)
            normalized.append({
                "label": item.get("label") or f"Option {i + 1}",
                "style": item.get("style") or "general",
                "text": text,
            })
        elif isinstance(item, str) and item.strip():
            meta = DRAFT_STYLES[i] if i < len(DRAFT_STYLES) else (f"Option {i+1}", "general", "")
            label, style, _ = meta
            normalized.append({
                "label": label,
                "style": style,
                "text": _finalize_draft_static(item, ref_url),
            })

    if not normalized and fallback_text:
        normalized.append({"label": "Default", "style": "general", "text": fallback_text})

    return normalized


def _finalize_draft_static(draft: str, ref_url: str) -> str:
    draft = _clean_ai_punctuation(draft)
    draft = re.sub(r"\n\nReference:\s*https?://[^\s]+", "", draft, flags=re.IGNORECASE)
    if ref_url and is_usable_reference_url(ref_url) and ref_url not in draft:
        draft = f"{draft.rstrip()}\n\nReference: {ref_url}"
    return draft


def _clean_ai_punctuation(text: str) -> str:
    """Strip the em/en dashes and dash-as-connector style that reads as AI."""
    if not text:
        return text

    def _to_sentence(match: "re.Match") -> str:
        # "word — Next" -> "word. Next" (capitalize the following word)
        return f". {match.group(1).upper()}"

    # Em / en dash with spaces -> sentence break, capitalizing the next word
    text = re.sub(r"\s+[—–]\s+([a-z])", _to_sentence, text)
    # Remaining em/en dashes (no surrounding spaces) -> comma
    text = text.replace("—", ", ").replace("–", ", ")
    # " word - word " hyphen used as a connector (keep real hyphenated words)
    text = re.sub(r"(\w)\s+-\s+([a-z])", lambda m: f"{m.group(1)}, {m.group(2)}", text)
    text = re.sub(r"(\w)\s+-\s+([A-Z])", lambda m: f"{m.group(1)}. {m.group(2)}", text)
    # Collapse any doubled punctuation we may have introduced
    text = re.sub(r"\.\s*\.", ".", text)
    text = re.sub(r",\s*,", ",", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


class TrendAnalysisService:
    """Analyze X posts to determine why a topic is trending and generate LinkedIn content."""

    @property
    def is_configured(self) -> bool:
        return claude_service.is_configured

    def _format_posts_for_prompt(self, posts: list[dict]) -> str:
        lines = []
        for i, post in enumerate(posts[:8], 1):
            comments = post.get("comments", post.get("replies", 0))
            lines.append(
                f"Post {i} [{post.get('source', 'source')}]:\n"
                f"  Author: {post.get('author_name', 'Unknown')} ({post.get('author_handle', 'unknown')})\n"
                f"  Text: {post.get('text', '')}\n"
                f"  Date: {post.get('created_at', 'unknown')}\n"
                f"  Engagement: {post.get('likes', 0)} upvotes/likes, {comments} comments\n"
            )
        return "\n".join(lines)

    def _best_reference(self, posts: list[dict]) -> dict:
        """Pick the most credible link to cite.

        Research papers beat social posts when both exist — drafts should cite
        the primary source (arxiv, pubmed), not a viral tweet about something else.
        """

        def _engagement(p: dict) -> float:
            return (p.get("likes", 0) or 0) + (p.get("retweets", 0) or 0) * 3 + (
                p.get("comments", p.get("replies", 0)) or 0
            ) * 2

        def _url(p: dict) -> str:
            return (p.get("post_url") or "").strip()

        papers = [
            p for p in posts
            if (
                p.get("content_type") == RESEARCH_PAPER
                or p.get("source") in ("arxiv", "pubmed", "preprint")
            )
            and is_usable_reference_url(_url(p))
        ]
        if papers:
            top = max(papers, key=lambda p: p.get("_relevance", 0.0))
            return {"url": _url(top), "source_post": top}

        buzz = [
            p for p in posts
            if p.get("content_type") == "research_buzz"
            and text_links_to_paper(p.get("text", ""))
            and is_usable_reference_url(_url(p))
        ]
        if buzz:
            top = max(buzz, key=lambda p: (_engagement(p), p.get("_relevance", 0.0)))
            for match in _URL_RE.findall(top.get("text", "")):
                paper_url = match.rstrip(".,);]")
                if text_links_to_paper(paper_url) and is_usable_reference_url(paper_url):
                    return {"url": paper_url, "source_post": top}
            return {"url": _url(top), "source_post": top}

        article_posts = [
            p
            for p in posts
            if p.get("source") in ("news", "industry", "devto") and is_usable_reference_url(_url(p))
        ]
        if article_posts:
            top = max(article_posts, key=lambda p: p.get("_relevance", 0.0))
            return {"url": _url(top), "source_post": top}

        engaged = sorted(
            posts,
            key=lambda p: p.get("likes", 0) + p.get("comments", p.get("replies", 0)) * 2,
            reverse=True,
        )

        for post in engaged:
            for match in _URL_RE.findall(post.get("text", "")):
                url = match.rstrip(".,);]")
                if is_usable_reference_url(url) and not any(host in url for host in _BAD_LINK_HOSTS):
                    return {"url": url, "source_post": post}

        for post in engaged:
            url = _url(post)
            if post.get("source") in ("reddit", "hackernews") and is_usable_reference_url(url):
                return {"url": url, "source_post": post}

        for post in engaged:
            url = _url(post)
            if is_usable_reference_url(url):
                return {"url": url, "source_post": post}

        return {"url": "", "source_post": {}}

    def _fallback_analysis(
        self,
        topic_name: str,
        posts: list[dict],
        parsed: ParsedObjective,
    ) -> dict:
        top_post = max(posts, key=lambda p: p.get("likes", 0) + p.get("retweets", 0), default={})
        focus = parsed.focus_domains[0] if parsed.focus_domains else parsed.content_goal
        proof = parsed.proof_points[0] if parsed.proof_points else None
        proof_clause = f" In my own work ({proof[:100]}), I keep hitting the same trade-offs." if proof else ""
        reference = self._best_reference(posts)
        ref_url = reference.get("url", "")
        ref_clause = f"\n\nReference: {ref_url}" if ref_url else ""

        draft = (
            f"Most teams treat {topic_name.lower()} as solved. It isn't.\n\n"
            f"There's a live discussion this week about what actually works in practice, "
            f"not the polished version.{proof_clause}\n\n"
            f"If you work in {focus}, the useful question isn't whether this is trending. "
            f"It's which part maps to a problem you're already paying for.\n\n"
            f"What's your take?{ref_clause}"
        )

        draft = _finalize_draft_static(draft, ref_url)

        return {
            "why_trending": (
                f"Practitioners are actively debating {topic_name} in ways that connect to {focus}."
            ),
            "specific_event": top_post.get("text", f"Active discussion on {topic_name}.")[:300],
            "why_matters": (
                f"For someone focused on {parsed.content_goal}, this conversation is about "
                f"what's changing in practice, not just the headline."
            ),
            "linkedin_angle": (
                f"Tie the trend to one concrete lesson from your experience, framed for {focus}."
            ),
            "linkedin_draft": None,
            "linkedin_drafts": [],
            "reference_url": ref_url,
        }

    async def analyze_topic_discovery(
        self,
        topic_name: str,
        query_used: str,
        posts: list[dict],
        parsed: ParsedObjective,
    ) -> dict:
        """Lightweight topic analysis for discovery — no LinkedIn drafts (saves LLM cost)."""
        filtered_posts = filter_relevant_posts(posts, parsed)
        if not filtered_posts:
            return self._fallback_analysis(topic_name, posts, parsed)

        if not self.is_configured:
            return self._fallback_analysis(topic_name, filtered_posts, parsed)

        posts_text = self._format_posts_for_prompt(filtered_posts)
        writer_context = parsed.prompt_block()
        reference = self._best_reference(filtered_posts)
        ref_url = reference.get("url", "")

        prompt = f"""Analyze this trending topic for a professional who wants LinkedIn content ideas. Do NOT write full posts yet.

{writer_context}

TOPIC: "{topic_name}"

Evidence posts (filtered to match the goal):
{posts_text}

Return JSON with these exact keys:
{{
  "why_trending": "1-2 sentences: why this matters for THIS user's goal right now",
  "specific_event": "The concrete event/debate/finding from the evidence",
  "why_matters": "Why someone with this author's goal should care",
  "linkedin_angle": "One sharp angle tied to their background (1-2 sentences)"
}}"""

        try:
            content = claude_service.complete(
                prompt=prompt,
                system="You analyze trending professional topics. Output only valid JSON.",
                model=settings.anthropic_model_fast,
                max_tokens=800,
                temperature=0.5,
            )
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\n?", "", content)
                content = re.sub(r"\n?```$", "", content)
            result = json.loads(content)
            required = ["why_trending", "specific_event", "why_matters", "linkedin_angle"]
            if all(k in result for k in required):
                result["linkedin_draft"] = None
                result["linkedin_drafts"] = []
                result["reference_url"] = ref_url
                return result
        except Exception as e:
            logger.error(f"Topic discovery analysis failed for '{topic_name}': {e}")

        return self._fallback_analysis(topic_name, filtered_posts, parsed)

    async def analyze_topic(
        self,
        topic_name: str,
        query_used: str,
        posts: list[dict],
        parsed: ParsedObjective,
    ) -> dict:
        """Alias for discovery-only analysis (drafts are generated on demand)."""
        return await self.analyze_topic_discovery(
            topic_name, query_used, posts, parsed
        )

    async def generate_drafts(
        self,
        topic_name: str,
        posts: list[dict],
        parsed: ParsedObjective,
        style_keys: Optional[List[str]] = None,
    ) -> dict:
        """Generate LinkedIn post drafts on demand for selected styles only."""
        style_keys = style_keys or active_run_settings().draft_styles
        style_keys = [k for k in style_keys if k in {s[0] for s in DRAFT_STYLES}]
        if not style_keys:
            style_keys = [DRAFT_STYLES[0][0]]

        filtered_posts = filter_relevant_posts(posts, parsed)
        if not filtered_posts:
            filtered_posts = posts

        reference = self._best_reference(filtered_posts)
        ref_url = reference.get("url", "")

        if not self.is_configured:
            fb = self._fallback_analysis(topic_name, filtered_posts, parsed)
            drafts = _normalize_drafts(
                [{"label": "Default", "style": "general", "text": fb.get("linkedin_draft") or ""}],
                ref_url,
                "",
            )
            return {"linkedin_drafts": drafts, "linkedin_draft": drafts[0]["text"] if drafts else ""}

        posts_text = self._format_posts_for_prompt(filtered_posts)
        ref_line = (
            f'\nPRIMARY REFERENCE (use this exact URL in Reference line when the post cites research): {ref_url}'
            if ref_url
            else "\n(No clean external link. Do NOT invent one.)"
        )
        count = len(style_keys)

        prompt = f"""Write {count} DISTINCT LinkedIn post drafts for this professional.

{parsed.prompt_block()}

TOPIC: "{topic_name}"

Evidence:
{posts_text}
{ref_line}

DRAFT STYLES (one draft per style listed):
{_draft_styles_block(style_keys)}

STRUCTURE per draft (no labels in output):
1. HOOK (line 1, under 12 words)
2. Blank line
3. CONTEXT (1-2 sentences)
4. INSIGHT (2-4 short lines)
5. PROOF (optional, 1-2 sentences from real background only)
6. TAKEAWAY (1 sentence)
7. ENGAGEMENT QUESTION (last line)
8. Reference line if URL exists: "Reference: <url>" — when evidence includes a research paper, cite the paper URL (arxiv/pubmed), NOT an unrelated viral X post.

RULES: human practitioner voice, short paragraphs, no em dashes, no AI clichés ({", ".join(BANNED_DRAFT_PATTERNS[:5])}…), 130-200 words each.

Return JSON:
{{
  "linkedin_drafts": [
    {{"label": "...", "style": "...", "text": "full post"}},
    ... ({count} total)
  ]
}}"""

        try:
            content = claude_service.complete(
                prompt=prompt,
                system=(
                    "Expert LinkedIn ghostwriter. Output only valid JSON with linkedin_drafts array."
                ),
                max_tokens=min(4096, 900 * count),
                temperature=0.75,
            )
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\n?", "", content)
                content = re.sub(r"\n?```$", "", content)
            result = json.loads(content)
            raw = result.get("linkedin_drafts") or []
            drafts = _normalize_drafts(raw, ref_url, "")
            return {
                "linkedin_drafts": drafts,
                "linkedin_draft": drafts[0]["text"] if drafts else "",
                "reference_url": ref_url,
            }
        except Exception as e:
            logger.error(f"Draft generation failed for '{topic_name}': {e}")
            raise

    def _finalize_draft(self, draft: str, ref_url: str) -> str:
        """Strip AI punctuation and guarantee the reference link is present."""
        draft = _clean_ai_punctuation(draft)
        if ref_url and ref_url not in draft:
            draft = f"{draft.rstrip()}\n\nReference: {ref_url}"
        return draft

    async def regenerate_draft(
        self,
        topic_name: str,
        posts: list[dict],
        parsed: ParsedObjective,
        previous_draft: str = "",
        why_trending: str = "",
        specific_event: str = "",
        linkedin_angle: str = "",
    ) -> str:
        """Produce a fresh, distinctly different LinkedIn draft for a topic."""
        reference = self._best_reference(posts)
        ref_url = reference.get("url", "")

        if not self.is_configured:
            return ""

        ref_line = (
            f'\nREFERENCE LINK to cite at the end: {ref_url}'
            if ref_url
            else "\n(No clean external link available. Do NOT invent one.)"
        )
        prev_block = (
            f"\n\nPREVIOUS DRAFT (write something clearly DIFFERENT, new hook and angle):\n{previous_draft}"
            if previous_draft
            else ""
        )

        prompt = f"""Write a fresh LinkedIn post for this professional. A new variation, different hook and structure from before.

{parsed.prompt_block()}

TOPIC: "{topic_name}"
WHY IT MATTERS: {why_trending}
SPECIFIC EVENT/FINDING: {specific_event}
SUGGESTED ANGLE: {linkedin_angle}
{ref_line}{prev_block}

STRUCTURE (no labels in output):
1. HOOK (line 1, standalone, under 12 words): a fresh, scroll-stopping opener distinct from the previous draft.
2. Blank line.
3. CONTEXT: the specific event/finding, 1-2 short sentences.
4. INSIGHT: the author's POV, 2-4 short lines, what most people miss.
5. PROOF (optional): ONE real detail from their background. Never invent.
6. TAKEAWAY: one crisp line.
7. ENGAGEMENT QUESTION: a specific question on the last line.
8. If a reference link exists, add it on its own final line as: "Reference: <url>"

RULES:
- Sound like a sharp human practitioner. Short sentences, lots of white space.
- NEVER use the em dash (—), en dash (–), or " - " as a connector. Use periods/commas.
- Do NOT use these phrases: {", ".join(BANNED_DRAFT_PATTERNS)}
- 0-2 hashtags max, 0-1 emoji max. No bullet lists. No hype.
- 130-200 words. Ground every claim in the evidence or the stated background.
Output plain text only (the post)."""

        try:
            draft = claude_service.complete(
                prompt=prompt,
                system=(
                    "You are an expert LinkedIn ghostwriter. You write specific, "
                    "human, scroll-stopping posts and never use em dashes or AI clichés. "
                    "Output plain text only."
                ),
                max_tokens=1024,
                temperature=0.9,
            )
            draft = draft.strip()
            if draft.startswith("```"):
                draft = re.sub(r"^```[a-z]*\n?", "", draft)
                draft = re.sub(r"\n?```$", "", draft)
            return self._finalize_draft(draft, ref_url)
        except Exception as e:
            logger.error(f"Draft regeneration failed for '{topic_name}': {e}")
            return previous_draft or self._fallback_analysis(
                topic_name, posts, parsed
            )["linkedin_draft"]

    async def _rewrite_draft(
        self, draft: str, parsed: ParsedObjective, topic_name: str
    ) -> str:
        try:
            rewritten = claude_service.complete(
                prompt=f"""Rewrite this LinkedIn draft to sound human and specific. Keep facts, change voice.

Author context:
{parsed.prompt_block()}

Topic: {topic_name}

Draft to rewrite:
{draft}

Rules: strong standalone hook on line 1, short sentences, lots of white space, end with a
specific question. NEVER use em dashes (—), en dashes, or " - " as connectors. No AI clichés.
Max 200 words. Stay aligned to the CONTENT GOAL.""",
                system="Rewrite LinkedIn posts in a natural human voice. No em dashes. Output plain text only.",
                max_tokens=800,
                temperature=0.6,
            )
            return _clean_ai_punctuation(rewritten)
        except Exception:
            return _clean_ai_punctuation(draft)


trend_analysis_service = TrendAnalysisService()
