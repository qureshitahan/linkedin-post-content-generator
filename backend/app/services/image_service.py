"""LinkedIn post image generation — Claude crafts prompts, OpenAI GPT Image renders.

Designed LinkedIn graphics (charts, slides, illustrations) tied to each post — not AI stock photos.
"""

import base64
import json
import logging
import os
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

You are designing a LinkedIn post image — like a Canva slide, carousel cover, or clean chart.
NOT a photorealistic stock photo. AI photos of people in hallways look fake and unprofessional.

What works on LinkedIn B2B/healthcare posts:
- A clean bar or line chart that visualizes the post's key claim
- A stat slide with one big number and short label
- A headline slide with the hook in bold typography
- A flat illustration of the concept (multi-site ops, district layer, consolidation)
- A simple before/after or with-vs-without comparison graphic (flat design, not icon org charts)

Rules:
- The image must match the SPECIFIC visual concept provided — not a generic scene
- Flat, designed, polished — credible LinkedIn creator aesthetic
- NO photorealistic people, NO person from behind, NO walking down corridors, NO holding tablets
- NO pharmacy/hospital stock photo scenes unless explicitly requested
- NO org charts with icon nodes and connecting lines
- NO random metaphors (sand, fog, bridges, surreal)
- Text on image: only when the format requires it — spell exact short text in the prompt
- Landscape 16:9, generous whitespace, professional palette (navy, white, teal, gray)"""

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

STOCK_PHOTO_CLICHES = (
    "from behind",
    "back view of a man",
    "back view of a person",
    "walking down the corridor",
    "walking down the hallway",
    "holding a tablet",
    "holding tablet",
    "stock photo",
    "photorealistic man",
    "photorealistic person",
    "hospital corridor",
    "pharmacy sign",
    "candid workplace photo",
    "professional candid",
)

# Designed LinkedIn formats only — no AI stock photos
VISUAL_FORMATS: dict[str, dict] = {
    "minimal_chart": {
        "uses_text": False,
        "instruction": (
            "Simple professional bar or line chart on a clean slide background that visualizes "
            "the post's core data point or comparison. Minimal axis labels, polished LinkedIn slide look."
        ),
    },
    "stat_slide": {
        "uses_text": True,
        "instruction": (
            "Stat highlight slide — one large number or range as hero typography, "
            "optional 3-5 word sublabel, clean solid or gradient background."
        ),
    },
    "text_slide": {
        "uses_text": True,
        "instruction": (
            "Headline slide — the post hook in bold sans-serif (max 10 words) on a clean background "
            "with one small flat accent icon related to the topic."
        ),
    },
    "comparison_graphic": {
        "uses_text": True,
        "instruction": (
            "With-vs-without or before/after comparison — two columns or split layout using flat design, "
            "short labels, simple shapes. Shows the contrast argued in the post. NOT an icon org chart."
        ),
    },
    "flat_illustration": {
        "uses_text": False,
        "instruction": (
            "Clean flat vector illustration of the post's concept (e.g. district layer connecting "
            "sites, multi-location ops). Modern minimal style, no photorealistic faces."
        ),
    },
    "simple_infographic": {
        "uses_text": True,
        "instruction": (
            "Single-insight infographic slide — 3 steps or 3 facts from the post with icons and "
            "short labels. Professional LinkedIn infographic, not a multi-tier hierarchy diagram."
        ),
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
    if any(term in lowered for term in STOCK_PHOTO_CLICHES):
        return True, "AI stock photo cliché"
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
        "chart": "minimal_chart",
        "graph": "minimal_chart",
        "infographic": "simple_infographic",
        "illustration": "flat_illustration",
        "comparison": "comparison_graphic",
        "visual_only": "flat_illustration",
        "place_photo": "flat_illustration",
        "people_at_work": "flat_illustration",
    }
    key = aliases.get(key, key)
    return key if key in VISUAL_FORMATS else "text_slide"


def _rank_formats(analysis: dict, draft_style: str) -> list[str]:
    """Best format order for this post — regenerate cycles through the list."""
    style = draft_style.strip().lower() or "general"
    has_stat = bool(analysis.get("stat_text")) or _has_stat(analysis.get("hook", ""))
    has_comparison = any(
        w in (analysis.get("post_theme", "") + analysis.get("hook", "")).lower()
        for w in ("vs", "without", "with vs", "before", "after", "while others", "break even", "2.0x", "8x", "4x")
    )

    order: list[str] = []
    suggested = _normalize_format_key(analysis.get("recommended_format", ""))
    if suggested:
        order.append(suggested)

    if has_stat:
        order.extend(["stat_slide", "minimal_chart"])
    if has_comparison:
        order.extend(["comparison_graphic", "minimal_chart"])
    if style == "analytical":
        order.extend(["minimal_chart", "stat_slide", "simple_infographic"])
    elif style == "provocative":
        order.extend(["text_slide", "comparison_graphic", "stat_slide"])
    elif style == "story":
        order.extend(["text_slide", "flat_illustration", "comparison_graphic"])
    elif style == "curious":
        order.extend(["text_slide", "simple_infographic"])
    elif style == "actionable":
        order.extend(["simple_infographic", "comparison_graphic", "minimal_chart"])

    order.extend(["text_slide", "flat_illustration", "minimal_chart", "comparison_graphic", "stat_slide", "simple_infographic"])

    seen: set[str] = set()
    ranked: list[str] = []
    for fmt in order:
        if fmt in VISUAL_FORMATS and fmt not in seen:
            if fmt == "stat_slide" and not has_stat and not analysis.get("stat_text"):
                continue
            seen.add(fmt)
            ranked.append(fmt)
    return ranked or ["text_slide"]


def _pick_visual_format(analysis: dict, draft_style: str, variation_seed: str = "") -> str:
    ranked = _rank_formats(analysis, draft_style)
    if not variation_seed:
        return ranked[0]
    idx = int(variation_seed[:8], 16) % len(ranked)
    return ranked[idx]


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
        "visual_concept": f"LinkedIn slide about: {hook[:100]}",
        "recommended_format": "text_slide",
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
                "visual_concept": str(data.get("visual_concept") or defaults["visual_concept"]).strip()[:300],
                "recommended_format": _normalize_format_key(
                    str(data.get("recommended_format") or "text_slide")
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
    prompt = f"""Plan ONE LinkedIn cover image for this draft. Return JSON only.
{topic_block}
Draft style: {draft_style or "general"}

Draft:
{draft_text[:2200]}

Formats (pick best): {formats_list}

Think: what single designed graphic would a healthcare operator post with this text?
NOT a stock photo of a person in a hallway.

Return exactly:
{{
  "industry": "e.g. healthcare, pharmacy",
  "hook": "opening hook in one line",
  "headline_text": "short text for a headline slide, max 10 words",
  "stat_text": "key stat if any (e.g. 60-80%), else empty",
  "post_theme": "one sentence on the post's core message",
  "visual_concept": "2 sentences describing EXACTLY what to design — e.g. bar chart comparing 8x vs 4x EBITDA with/without district supervisors on navy slide",
  "recommended_format": "best format key from the list"
}}"""

    try:
        raw = claude_service.complete(
            prompt=prompt,
            system=(
                "You plan LinkedIn slide/chart graphics. Never recommend stock photos or "
                "people in corridors. Return valid JSON only."
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
    return "Include on image: " + "; ".join(parts) if parts else "Do NOT include text, words, or typography in the image."


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
        chosen_format = _pick_visual_format(analysis, style_key, variation_seed)
        fmt_meta = VISUAL_FORMATS[chosen_format]
        rejection_note = ""
        concept = analysis.get("visual_concept") or analysis.get("post_theme") or analysis.get("hook")

        if claude_service.is_configured:
            for attempt in range(3):
                prompt = f"""Write one image generation prompt for a LinkedIn post cover image.
{topic_block}

EXACT VISUAL TO CREATE:
{concept}

FORMAT: {chosen_format}
{fmt_meta['instruction']}

POST:
- Industry: {analysis['industry']}
- Hook: {analysis['hook']}
- Theme: {analysis['post_theme']}
- Draft style: {label}
{_text_instruction(analysis, chosen_format)}

DRAFT TEXT:
{draft_text[:1800]}
{hint_block}
{rejection_note}

Instructions:
- Execute the EXACT VISUAL concept above as a designed slide/chart/illustration
- Flat designed graphic — NOT a photorealistic photo of a person
- Must directly support what this post is saying
- Professional LinkedIn B2B aesthetic, landscape 16:9"""

                try:
                    result = claude_service.complete(
                        prompt=prompt,
                        system=LINKEDIN_IMAGE_SYSTEM,
                        model=settings.anthropic_model,
                        max_tokens=550,
                        temperature=0.7,
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
                        "\nCRITICAL: Design a flat slide/chart/illustration only. "
                        "No people, no hallways, no tablets, no stock photos."
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
        fmt = chosen_format if chosen_format in VISUAL_FORMATS else "text_slide"
        meta = VISUAL_FORMATS[fmt]
        concept = info.get("visual_concept") or info.get("hook") or _draft_hook(draft_text)
        text_part = _text_instruction(info, fmt)
        base = (
            f"Professional LinkedIn {fmt} graphic, flat designed slide — NOT a photograph. "
            f"{meta['instruction']} Visual: {concept}. {text_part} "
            f"Navy and white palette, landscape 16:9, clean Canva-style layout."
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
