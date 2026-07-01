"""LinkedIn post image generation — Claude crafts prompts, OpenAI GPT Image renders.

Design-first LinkedIn graphics (stat cards, charts, slides) — not photorealistic AI photos.
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

LINKEDIN_IMAGE_SYSTEM = """You write image generation prompts for polished LinkedIn post graphics.
Output ONLY the prompt text — no quotes around the whole prompt, no preamble, no markdown.

Design like a professional LinkedIn carousel slide or Canva template — NOT an AI photo.

PREFERRED formats (pick ONE):
- Stat card: large bold number or claim as typography on a clean solid/gradient background
- Carousel slide: headline text + small flat icon or minimal illustration
- Minimal chart: simple clean bar/line chart that supports the post's point
- Flat illustration: simple vector-style drawing (healthcare, ops, business) — not photorealistic
- Comparison graphic: two-column or before/after using flat shapes, not photos

TEXT ON IMAGE (encouraged):
- Include a short headline or stat from the post (max ~10 words)
- Spell the exact text clearly in the prompt so the model renders it
- Large readable sans-serif typography, high contrast

AVOID (looks fake on LinkedIn):
- Photorealistic people, faces, hands, or "documentary" workplace photos
- Random metaphors (sand, fog, bridges, puzzle pieces, surreal scenes)
- Generic org charts with icon nodes and connecting lines
- Overly cinematic or artsy imagery

Style rules:
- Flat design, clean layout, generous whitespace
- Professional palette: navy, white, teal, soft gray, one accent color
- Landscape 16:9, looks like a designed social graphic — crisp and intentional
- No logos or watermarks"""

ORG_CHART_PROMPT_TERMS = (
    "organizational chart",
    "org chart",
    "supervisor node",
    "executive node",
    "location icons connected",
    "icon cluster",
    "scattered icons connected by lines",
)

PHOTO_SLOP_TERMS = (
    "photorealistic person",
    "realistic human",
    "human face",
    "documentary photograph",
    "editorial photograph",
    "cinematic",
    "film still",
    "sand ",
    " sand",
    "foggy",
    "puzzle piece",
    "empty bridge",
    "golden hour portrait",
    "over-the-shoulder photo",
    "silhouette standing",
)

LINKEDIN_VISUAL_FORMATS = (
    "stat_card — bold stat or claim as large typography (best when post has numbers or a punchy hook)",
    "carousel_slide — LinkedIn slide with headline text and a small flat illustration",
    "minimal_chart — clean simple chart supporting the post's argument",
    "flat_illustration — minimal vector drawing related to the topic",
    "comparison_graphic — flat side-by-side showing the contrast in the post",
    "quote_hook — large headline text from the post on a professional background",
)

FORMAT_DEFAULT = "carousel_slide"

DRAFT_STYLE_VISUALS = {
    "provocative": "Bold hook slide — large provocative headline text, strong color block, minimal accent graphic.",
    "analytical": "Evidence-led — stat, chart, or data-forward slide with clean typography.",
    "story": "Personal POV — quote-style headline with warm flat illustration, not a photo.",
    "curious": "Question-led — big question text on clean background with simple icon.",
    "actionable": "Practical takeaway — checklist-style or step graphic with clear headline.",
    "general": "Professional LinkedIn carousel slide tied to the post hook.",
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
    if any(term in lowered for term in PHOTO_SLOP_TERMS):
        return True, "photorealistic or metaphor slop"
    return False, ""


def _style_visual_mandate(draft_style: str) -> str:
    return DRAFT_STYLE_VISUALS.get(draft_style.strip().lower(), DRAFT_STYLE_VISUALS["general"])


def _draft_hook(draft_text: str) -> str:
    for line in draft_text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("http"):
            return stripped[:120]
    return draft_text[:120]


def _parse_visual_analysis(raw: str, draft_text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE)
    hook = _draft_hook(draft_text)
    defaults = {
        "industry": "professional business",
        "hook": hook,
        "headline_text": hook[:80],
        "stat_text": "",
        "concrete_subjects": [],
        "post_theme": "",
        "recommended_format": FORMAT_DEFAULT,
    }
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return {
                "industry": str(data.get("industry") or defaults["industry"]).strip(),
                "hook": str(data.get("hook") or hook).strip(),
                "headline_text": str(data.get("headline_text") or data.get("hook") or hook)[:80].strip(),
                "stat_text": str(data.get("stat_text") or "").strip()[:40],
                "concrete_subjects": [
                    str(s).strip() for s in (data.get("concrete_subjects") or []) if str(s).strip()
                ][:6],
                "post_theme": str(data.get("post_theme") or "").strip(),
                "recommended_format": str(data.get("recommended_format") or FORMAT_DEFAULT).strip(),
            }
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return defaults


def _analyze_draft_for_visual(draft_text: str, topic_name: str, draft_style: str) -> dict:
    if not claude_service.is_configured:
        return _parse_visual_analysis("", draft_text)

    topic_block = f"\nTopic: {topic_name}" if topic_name else ""
    formats_block = "\n".join(f"- {fmt}" for fmt in LINKEDIN_VISUAL_FORMATS)
    prompt = f"""Analyze this LinkedIn draft for a DESIGNED graphic (not a photo). Return JSON only.
{topic_block}
Draft style: {draft_style or "general"}

Draft:
{draft_text[:2200]}

Choose recommended_format from:
{formats_block}

Return exactly:
{{
  "industry": "e.g. healthcare, pharmacy",
  "hook": "opening hook in one line",
  "headline_text": "short text to display ON the image, max 10 words, from hook or key claim",
  "stat_text": "key number or percentage if any, else empty string",
  "concrete_subjects": ["2-4 visual subjects for a flat illustration, e.g. pharmacy, district manager"],
  "post_theme": "one sentence summary",
  "recommended_format": "e.g. stat_card or carousel_slide"
}}"""

    try:
        raw = claude_service.complete(
            prompt=prompt,
            system="Plan LinkedIn slide graphics. Return valid JSON only. Prefer stat_card when post has numbers.",
            model=settings.anthropic_model_fast,
            max_tokens=400,
            temperature=0.2,
        )
        return _parse_visual_analysis(raw, draft_text)
    except Exception as e:
        logger.warning(f"Visual analysis failed, using defaults: {e}")
        return _parse_visual_analysis("", draft_text)


def _text_block(analysis: dict) -> str:
    parts = []
    if analysis.get("stat_text"):
        parts.append(f'Stat to emphasize: "{analysis["stat_text"]}"')
    if analysis.get("headline_text"):
        parts.append(f'Headline text on image: "{analysis["headline_text"]}"')
    return "\n".join(parts) if parts else f'Headline text on image: "{analysis.get("hook", "")[:80]}"'


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
    ) -> str:
        hint_block = f"\nUser's visual preference: {user_hint}" if user_hint.strip() else ""
        topic_block = f"\nTopic: {topic_name}" if topic_name else ""
        style_key = draft_style.strip().lower() or "general"
        label = draft_label.strip() or style_key.replace("_", " ").title()
        analysis = _analyze_draft_for_visual(draft_text, topic_name, style_key)
        subjects = ", ".join(analysis["concrete_subjects"]) or analysis["industry"]
        rejection_note = ""

        if claude_service.is_configured:
            for attempt in range(3):
                prompt = f"""Write one image generation prompt for a LinkedIn post graphic.
{topic_block}

POST ANALYSIS:
- Industry: {analysis['industry']}
- Theme: {analysis['post_theme'] or analysis['hook']}
- Format: {analysis['recommended_format']}
- Draft style ({label}): {_style_visual_mandate(style_key)}
- Illustration subjects (flat, not photos): {subjects}
{_text_block(analysis)}

FULL DRAFT:
{draft_text[:2000]}
{hint_block}
{rejection_note}

Instructions:
- Design a polished LinkedIn carousel slide / social graphic — flat design, NOT a photo
- Include the headline text (and stat if provided) spelled exactly in the prompt
- Simple clean layout: bold typography, solid or gradient background, optional minimal chart or icon
- Must clearly relate to this post's topic and hook
- NO photorealistic people, faces, hands, or random metaphors
- NO org-chart icon diagrams
- Specify colors, layout, and typography style (clean sans-serif, professional)"""

                try:
                    result = claude_service.complete(
                        prompt=prompt,
                        system=LINKEDIN_IMAGE_SYSTEM,
                        model=settings.anthropic_model,
                        max_tokens=550,
                        temperature=0.75,
                    ).strip()
                    bad, reason = _is_bad_prompt(result)
                    if not bad:
                        return result
                    logger.warning(
                        "Rejected image prompt (%s, attempt %s, style=%s)",
                        reason,
                        attempt + 1,
                        style_key,
                    )
                    rejection_note = (
                        "\nCRITICAL: Previous attempt was rejected. Create a flat LinkedIn slide graphic "
                        "with headline text — no photos, no sand/fog/metaphors, no org-chart icons."
                    )
                except Exception as e:
                    logger.warning(f"Claude image prompt failed, using fallback: {e}")
                    break

        return self._fallback_prompt(draft_text, user_hint, draft_style, analysis)

    async def craft_edit_prompt(
        self,
        previous_prompt: str,
        edit_instruction: str,
        draft_text: str = "",
        draft_style: str = "",
    ) -> str:
        if claude_service.is_configured:
            style_note = _style_visual_mandate(draft_style) if draft_style else ""
            rejection_note = ""
            for attempt in range(3):
                prompt = f"""Revise this LinkedIn graphic prompt based on user feedback.

ORIGINAL PROMPT:
{previous_prompt}

USER REQUESTED CHANGES:
{edit_instruction}

POST (context):
{draft_text[:800]}
{f"Style: {style_note}" if style_note else ""}
{rejection_note}

Keep it a designed LinkedIn slide/graphic — flat, professional, text allowed.
No photorealistic photos or random metaphors.
Output ONLY the new prompt."""

                try:
                    result = claude_service.complete(
                        prompt=prompt,
                        system=LINKEDIN_IMAGE_SYSTEM,
                        model=settings.anthropic_model,
                        max_tokens=550,
                        temperature=0.75,
                    ).strip()
                    bad, _ = _is_bad_prompt(result)
                    if not bad:
                        return result
                    rejection_note = (
                        "\nCRITICAL: Use flat slide design with text — no AI photos or org charts."
                    )
                except Exception as e:
                    logger.warning(f"Claude edit prompt failed: {e}")
                    break

        return f"{previous_prompt}. Changes: {edit_instruction}"[:900]

    def _fallback_prompt(
        self,
        draft_text: str,
        user_hint: str,
        draft_style: str = "",
        analysis: Optional[dict] = None,
    ) -> str:
        info = analysis or _parse_visual_analysis("", draft_text)
        headline = info.get("headline_text") or info.get("hook") or _draft_hook(draft_text)
        stat = info.get("stat_text") or ""
        industry = info.get("industry") or "business"
        stat_part = f'Large stat text: "{stat}". ' if stat else ""
        base = (
            f"Professional LinkedIn carousel slide graphic, flat design, {industry} topic. "
            f"{stat_part}Headline text: \"{headline[:80]}\". "
            f"Clean sans-serif typography on navy and white background, minimal flat icon, "
            f"generous whitespace, 16:9 landscape, looks like a designed Canva template, "
            f"not a photograph, no realistic people."
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
