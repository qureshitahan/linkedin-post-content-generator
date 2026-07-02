"""LinkedIn post image generation — Claude crafts prompts, OpenAI GPT Image renders.

Varied LinkedIn-native visuals: slides, charts, photos, illustrations — rotated per generation.
"""

import base64
import json
import logging
import os
import random
import re
import uuid
from pathlib import Path
from typing import Optional

import httpx
from openai import OpenAI

from app.config import settings
from app.services.claude import claude_service

logger = logging.getLogger(__name__)

AZURE_IMAGES_DIR = Path("/home/site/data/generated_images")
LOCAL_IMAGES_DIR = Path(__file__).resolve().parent.parent.parent / "generated_images"
IMAGES_DIR = AZURE_IMAGES_DIR if Path("/home/site/data").is_dir() else LOCAL_IMAGES_DIR
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
OPENAI_PLACEHOLDERS = frozenset(
    {
        "",
        "your_openai_api_key_here",
        "none",
        "null",
        "undefined",
        "paste from backend/.env",
    }
)

LINKEDIN_IMAGE_SYSTEM = """You write image generation prompts for LinkedIn post cover images.
Output ONLY the prompt text — no preamble, no markdown.

Think like someone who posts on LinkedIn every few days — each image looks DIFFERENT:
sometimes a designed slide with text, sometimes a chart, sometimes a photo of a real place,
sometimes people at work, sometimes a flat illustration — but always professional and on-topic.

Pick the assigned visual format and execute it well. Do NOT default to the same layout every time.

Quality bar:
- Polished, credible, scroll-worthy — like top LinkedIn creators and B2B brands
- Clearly related to the post's industry and message
- Clean composition, intentional color palette

AVOID:
- Generic org charts with icon nodes and connecting lines
- Random unrelated metaphors (sand, fog, empty bridges, puzzle pieces, surreal art)
- Uncanny close-up AI faces — if people appear, use from-behind, wide shot, or stock-photo distance
- Cheesy clip art or obvious template spam

Text on image: ONLY when the assigned format calls for it. Otherwise no text."""

ORG_CHART_PROMPT_TERMS = (
    "organizational chart",
    "org chart",
    "supervisor node",
    "executive node",
    "location icons connected",
    "icon cluster",
    "scattered icons connected by lines",
)

METAPHOR_SLOP_TERMS = (
    "sand ",
    " sand",
    "sand grains",
    "foggy",
    "puzzle piece",
    "empty bridge",
    "surreal",
    "floating in void",
)

# Each format: uses_text, instruction template
VISUAL_FORMATS: dict[str, dict] = {
    "visual_only": {
        "uses_text": False,
        "instruction": (
            "A strong topical image with NO text — professional photo or clean illustration that "
            "supports the post hook. Real industry setting or symbolic object directly tied to the topic."
        ),
    },
    "place_photo": {
        "uses_text": False,
        "instruction": (
            "Professional stock-quality photo of a real workplace or industry setting from the post "
            "(pharmacy interior, clinic, ops office, retail back room). Natural light, wide shot, no text."
        ),
    },
    "people_at_work": {
        "uses_text": False,
        "instruction": (
            "Professional candid workplace photo — team or manager in context (from behind or wide shot, "
            "avoid front-facing close-ups). Clearly in the post's industry. No text overlay."
        ),
    },
    "flat_illustration": {
        "uses_text": False,
        "instruction": (
            "Clean flat vector illustration related to the post topic. Modern, minimal, professional "
            "color palette. No photorealistic faces. No text unless format requires."
        ),
    },
    "minimal_chart": {
        "uses_text": False,
        "instruction": (
            "Simple clean chart or graph (bar, line, or comparison) on a professional background — "
            "visualizes the post's core point. Minimal labels, no paragraph text. Polished slide aesthetic."
        ),
    },
    "comparison_graphic": {
        "uses_text": False,
        "instruction": (
            "Side-by-side or before/after graphic showing the contrast in the post — flat design or "
            "split photo layout, NOT an org chart with icon nodes. No long text blocks."
        ),
    },
    "simple_infographic": {
        "uses_text": False,
        "instruction": (
            "Single-insight infographic — one clear visual idea with icons or shapes, not a multi-tier org chart. "
            "Professional LinkedIn infographic style."
        ),
    },
    "text_slide": {
        "uses_text": True,
        "instruction": (
            "LinkedIn carousel slide — one short headline (max 10 words) in bold sans-serif on a clean "
            "solid or gradient background, plus a small relevant flat icon or accent shape."
        ),
    },
    "stat_slide": {
        "uses_text": True,
        "instruction": (
            "Stat highlight slide — large number or percentage as hero typography, optional short subline, "
            "clean professional background. Only use if the post has a real stat or bold quantified claim."
        ),
    },
}

STYLE_FORMAT_WEIGHTS: dict[str, dict[str, float]] = {
    "provocative": {
        "visual_only": 1.8,
        "comparison_graphic": 1.5,
        "text_slide": 1.2,
        "place_photo": 1.3,
        "stat_slide": 1.0,
    },
    "analytical": {
        "minimal_chart": 2.0,
        "stat_slide": 1.8,
        "simple_infographic": 1.5,
        "text_slide": 0.8,
        "place_photo": 1.0,
    },
    "story": {
        "people_at_work": 2.0,
        "place_photo": 1.8,
        "visual_only": 1.5,
        "flat_illustration": 1.2,
        "text_slide": 0.6,
    },
    "curious": {
        "visual_only": 1.6,
        "flat_illustration": 1.5,
        "text_slide": 1.3,
        "comparison_graphic": 1.2,
    },
    "actionable": {
        "people_at_work": 1.8,
        "simple_infographic": 1.5,
        "minimal_chart": 1.3,
        "place_photo": 1.2,
        "text_slide": 1.0,
    },
}


def resolve_openai_api_key() -> str:
    return (os.environ.get("OPENAI_API_KEY") or settings.openai_api_key or "").strip()


def is_valid_openai_api_key(key: str) -> bool:
    normalized = key.strip().lower()
    if normalized in OPENAI_PLACEHOLDERS:
        return False
    return key.startswith("sk-")


def _is_bad_prompt(prompt: str) -> tuple[bool, str]:
    lowered = prompt.lower()
    if any(term in lowered for term in ORG_CHART_PROMPT_TERMS):
        return True, "org chart icons"
    if any(term in lowered for term in METAPHOR_SLOP_TERMS):
        return True, "unrelated metaphor"
    return False, ""


def _draft_hook(draft_text: str) -> str:
    for line in draft_text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("http"):
            return stripped[:120]
    return draft_text[:120]


def _has_stat(draft_text: str) -> bool:
    return bool(re.search(r"\d+\s*[%]|(?:\d+[\-–]\d+)|(?:\$\d)|(?:\d+\+?\s*(?:%|percent|pharmacies|clinics|sites|locations))", draft_text, re.I))


def _normalize_format_key(raw: str) -> str:
    key = raw.strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "stat_card": "stat_slide",
        "carousel_slide": "text_slide",
        "quote_hook": "text_slide",
        "minimal_chart": "minimal_chart",
        "comparison_graphic": "comparison_graphic",
        "flat_illustration": "flat_illustration",
        "topic_photo": "place_photo",
        "workplace_scene": "people_at_work",
        "research_evidence": "minimal_chart",
        "operational_snapshot": "people_at_work",
    }
    key = aliases.get(key, key)
    return key if key in VISUAL_FORMATS else "visual_only"


def _pick_visual_format(analysis: dict, draft_style: str) -> str:
    """Rotate formats so regenerations feel different — like posting on LinkedIn over time."""
    style_key = draft_style.strip().lower() or "general"
    style_weights = STYLE_FORMAT_WEIGHTS.get(style_key, {})

    candidates: list[str] = []
    weights: list[float] = []
    for fmt, meta in VISUAL_FORMATS.items():
        if fmt == "stat_slide" and not analysis.get("stat_text") and not _has_stat(analysis.get("hook", "")):
            continue
        w = style_weights.get(fmt, 1.0)
        if fmt in ("text_slide", "stat_slide"):
            w *= 0.7  # text slides less often overall
        candidates.append(fmt)
        weights.append(w)

    if not candidates:
        return "visual_only"

    # ~30% chance to use Claude's suggestion if valid
    suggested = _normalize_format_key(analysis.get("recommended_format", ""))
    if suggested in candidates and random.random() < 0.3:
        return suggested

    return random.choices(candidates, weights=weights, k=1)[0]


def _parse_visual_analysis(raw: str, draft_text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE)
    hook = _draft_hook(draft_text)
    stat_match = re.search(r"(\d+[\-–]\d+\s*%|\d+\s*%)", draft_text)
    stat_text = stat_match.group(1).strip() if stat_match else ""
    defaults = {
        "industry": "professional business",
        "hook": hook,
        "headline_text": hook[:80],
        "stat_text": stat_text,
        "concrete_subjects": [],
        "post_theme": "",
        "recommended_format": "visual_only",
    }
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return {
                "industry": str(data.get("industry") or defaults["industry"]).strip(),
                "hook": str(data.get("hook") or hook).strip(),
                "headline_text": str(data.get("headline_text") or hook)[:80].strip(),
                "stat_text": str(data.get("stat_text") or stat_text).strip()[:40],
                "concrete_subjects": [
                    str(s).strip() for s in (data.get("concrete_subjects") or []) if str(s).strip()
                ][:6],
                "post_theme": str(data.get("post_theme") or "").strip(),
                "recommended_format": _normalize_format_key(
                    str(data.get("recommended_format") or "visual_only")
                ),
            }
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return defaults


def _analyze_draft_for_visual(draft_text: str, topic_name: str, draft_style: str) -> dict:
    if not claude_service.is_configured:
        return _parse_visual_analysis("", draft_text)

    topic_block = f"\nTopic: {topic_name}" if topic_name else ""
    formats_list = ", ".join(VISUAL_FORMATS.keys())
    prompt = f"""Analyze this LinkedIn draft for cover image planning. Return JSON only.
{topic_block}
Draft style: {draft_style or "general"}

Draft:
{draft_text[:2200]}

Valid format keys: {formats_list}

Return exactly:
{{
  "industry": "e.g. healthcare, pharmacy",
  "hook": "opening hook in one line",
  "headline_text": "short headline IF a text slide fits, else empty string",
  "stat_text": "key number/percentage if any, else empty string",
  "concrete_subjects": ["2-4 things to show: places, roles, objects from the post"],
  "post_theme": "one sentence on what the post is about",
  "recommended_format": "one format key that fits — vary: not always text_slide"
}}"""

    try:
        raw = claude_service.complete(
            prompt=prompt,
            system=(
                "Plan varied LinkedIn cover images. Prefer photos or visuals without text when "
                "the post is narrative. Return valid JSON only."
            ),
            model=settings.anthropic_model_fast,
            max_tokens=400,
            temperature=0.3,
        )
        return _parse_visual_analysis(raw, draft_text)
    except Exception as e:
        logger.warning(f"Visual analysis failed, using defaults: {e}")
        return _parse_visual_analysis("", draft_text)


def _text_instruction(analysis: dict, fmt: str) -> str:
    meta = VISUAL_FORMATS[fmt]
    if not meta["uses_text"]:
        return "Do NOT include text, words, or typography in the image."
    parts = []
    if fmt == "stat_slide" and analysis.get("stat_text"):
        parts.append(f'Hero stat text: "{analysis["stat_text"]}"')
    headline = analysis.get("headline_text") or analysis.get("hook", "")
    if headline:
        parts.append(f'Headline text (max 10 words): "{headline[:80]}"')
    return "Include on image: " + "; ".join(parts) if parts else _text_instruction(analysis, "visual_only")


class ImageService:
    def __init__(self):
        self._client: Optional[OpenAI] = None
        self._client_key: str = ""

    @property
    def is_configured(self) -> bool:
        return is_valid_openai_api_key(resolve_openai_api_key())

    @property
    def key_last4(self) -> str:
        key = resolve_openai_api_key()
        return key[-4:] if len(key) >= 4 else ""

    def _get_client(self) -> OpenAI:
        key = resolve_openai_api_key()
        if not is_valid_openai_api_key(key):
            raise RuntimeError(
                "OpenAI API key is not configured. Add OPENAI_API_KEY to .env for image generation."
            )
        if self._client is None or self._client_key != key:
            self._client = OpenAI(api_key=key)
            self._client_key = key
        return self._client

    @property
    def prompt_engine_available(self) -> bool:
        return claude_service.is_configured

    async def craft_prompt_from_draft(
        self,
        draft_text: str,
        topic_name: str = "",
        user_hint: str = "",
        draft_style: str = "",
        draft_label: str = "",
        variation_seed: str = "",
    ) -> str:
        hint_block = f"\nUser's visual preference: {user_hint}" if user_hint.strip() else ""
        topic_block = f"\nTopic: {topic_name}" if topic_name else ""
        style_key = draft_style.strip().lower() or "general"
        label = draft_label.strip() or style_key.replace("_", " ").title()
        analysis = _analyze_draft_for_visual(draft_text, topic_name, style_key)
        chosen_format = _pick_visual_format(analysis, style_key)
        fmt_meta = VISUAL_FORMATS[chosen_format]
        subjects = ", ".join(analysis["concrete_subjects"]) or analysis["industry"]
        rejection_note = ""
        seed = variation_seed or uuid.uuid4().hex[:8]

        if claude_service.is_configured:
            for attempt in range(3):
                prompt = f"""Write one image generation prompt for a LinkedIn post cover image.
{topic_block}

ASSIGNED VISUAL FORMAT (follow exactly): {chosen_format}
Format direction: {fmt_meta['instruction']}

POST CONTEXT:
- Industry: {analysis['industry']}
- Hook: {analysis['hook']}
- Theme: {analysis['post_theme'] or analysis['hook']}
- Subjects/settings to draw from: {subjects}
- Draft style ({label}): match tone but keep the assigned format
- Variation seed: {seed} (use a fresh composition — different from a generic template)

TEXT: {_text_instruction(analysis, chosen_format)}

FULL DRAFT:
{draft_text[:2000]}
{hint_block}
{rejection_note}

Instructions:
- Must clearly relate to THIS post — a LinkedIn reader sees the connection immediately
- Execute the assigned format well; do NOT switch to a different format
- Professional, polished, varied — like real LinkedIn content
- NO org-chart icon diagrams; NO random metaphors (sand, fog, surreal)
- Specify composition, colors, medium (photo vs illustration vs chart), and mood"""

                try:
                    result = claude_service.complete(
                        prompt=prompt,
                        system=LINKEDIN_IMAGE_SYSTEM,
                        model=settings.anthropic_model,
                        max_tokens=550,
                        temperature=0.85,
                    ).strip()
                    bad, reason = _is_bad_prompt(result)
                    if not bad:
                        return result
                    logger.warning(
                        "Rejected image prompt (%s, format=%s, attempt=%s)",
                        reason,
                        chosen_format,
                        attempt + 1,
                    )
                    rejection_note = (
                        f"\nCRITICAL: Stay in format '{chosen_format}'. No org charts, no sand/fog/surreal metaphors."
                    )
                except Exception as e:
                    logger.warning(f"Claude image prompt failed, using fallback: {e}")
                    break

        return self._fallback_prompt(draft_text, user_hint, chosen_format, analysis)

    async def craft_edit_prompt(
        self,
        previous_prompt: str,
        edit_instruction: str,
        draft_text: str = "",
        draft_style: str = "",
    ) -> str:
        if claude_service.is_configured:
            rejection_note = ""
            for attempt in range(3):
                prompt = f"""Revise this LinkedIn cover image prompt from user feedback.

ORIGINAL:
{previous_prompt}

USER CHANGES:
{edit_instruction}

POST:
{draft_text[:800]}
{rejection_note}

Keep it professional and LinkedIn-native. Output ONLY the new prompt."""

                try:
                    result = claude_service.complete(
                        prompt=prompt,
                        system=LINKEDIN_IMAGE_SYSTEM,
                        model=settings.anthropic_model,
                        max_tokens=550,
                        temperature=0.85,
                    ).strip()
                    bad, _ = _is_bad_prompt(result)
                    if not bad:
                        return result
                    rejection_note = "\nCRITICAL: No org charts or unrelated metaphors."
                except Exception as e:
                    logger.warning(f"Claude edit prompt failed: {e}")
                    break

        return f"{previous_prompt}. Changes: {edit_instruction}"[:900]

    def _fallback_prompt(
        self,
        draft_text: str,
        user_hint: str,
        chosen_format: str,
        analysis: Optional[dict] = None,
    ) -> str:
        info = analysis or _parse_visual_analysis("", draft_text)
        fmt = chosen_format if chosen_format in VISUAL_FORMATS else "visual_only"
        meta = VISUAL_FORMATS[fmt]
        industry = info.get("industry") or "business"
        hook = info.get("hook") or _draft_hook(draft_text)
        text_part = _text_instruction(info, fmt)
        base = (
            f"LinkedIn post cover image, format: {fmt}. {meta['instruction']} "
            f"Topic: {industry}. Post about: {hook}. {text_part} "
            f"Landscape 16:9, polished professional quality."
        )
        if user_hint.strip():
            base += f" {user_hint.strip()}"
        return base[:900]

    def _image_quality(self) -> str:
        quality = settings.openai_image_quality.strip().lower()
        if settings.openai_image_model.startswith("gpt-image"):
            legacy = {"standard": "medium", "hd": "high"}
            return legacy.get(quality, quality)
        return quality

    def _save_image_bytes(self, content: bytes) -> str:
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid.uuid4().hex}.png"
        (IMAGES_DIR / filename).write_bytes(content)
        return filename

    async def generate(
        self,
        prompt: str,
        *,
        mode: str = "new",
        previous_prompt: str = "",
        edit_instruction: str = "",
        draft_text: str = "",
        topic_name: str = "",
        draft_style: str = "",
        draft_label: str = "",
        user_hint: str = "",
    ) -> dict:
        client = self._get_client()
        variation_seed = uuid.uuid4().hex[:8]

        if mode == "edit" and (previous_prompt or edit_instruction):
            final_prompt = await self.craft_edit_prompt(
                previous_prompt=previous_prompt or user_hint,
                edit_instruction=edit_instruction or user_hint,
                draft_text=draft_text,
                draft_style=draft_style,
            )
        elif user_hint.strip() and not previous_prompt:
            final_prompt = await self.craft_prompt_from_draft(
                draft_text=draft_text,
                topic_name=topic_name,
                user_hint=user_hint,
                draft_style=draft_style,
                draft_label=draft_label,
                variation_seed=variation_seed,
            )
        elif prompt.strip():
            final_prompt = prompt.strip()
        else:
            final_prompt = await self.craft_prompt_from_draft(
                draft_text=draft_text,
                topic_name=topic_name,
                user_hint=user_hint,
                draft_style=draft_style,
                draft_label=draft_label,
                variation_seed=variation_seed,
            )

        final_prompt = final_prompt[:4000]

        try:
            response = client.images.generate(
                model=settings.openai_image_model,
                prompt=final_prompt,
                size=settings.openai_image_size,
                quality=self._image_quality(),
                n=1,
            )
        except Exception as e:
            raise RuntimeError(f"Image generation failed: {e}") from e

        item = response.data[0]
        if item.b64_json:
            filename = self._save_image_bytes(base64.b64decode(item.b64_json))
        elif item.url:
            filename = await self._download_and_save(item.url)
        else:
            raise RuntimeError("OpenAI returned no image data")

        return {
            "image_url": f"/api/images/{filename}",
            "prompt_used": final_prompt,
            "filename": filename,
        }

    async def _download_and_save(self, url: str) -> str:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return self._save_image_bytes(resp.content)


image_service = ImageService()
