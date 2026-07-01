"""LinkedIn post image generation — Claude crafts prompts, OpenAI GPT Image renders.

Anthropic does not generate images. We use Claude (cheap Haiku) to turn LinkedIn
post text into a professional image prompt, then OpenAI's GPT Image model to render
on demand only (when the user clicks Generate — never automatic).
"""

import base64
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


def resolve_openai_api_key() -> str:
    """Prefer process env (Azure App Settings) over pydantic-loaded settings."""
    return (os.environ.get("OPENAI_API_KEY") or settings.openai_api_key or "").strip()


def is_valid_openai_api_key(key: str) -> bool:
    normalized = key.strip().lower()
    if normalized in OPENAI_PLACEHOLDERS:
        return False
    return key.startswith("sk-")

LINKEDIN_IMAGE_SYSTEM = """You write vivid, scroll-stopping image generation prompts for professional LinkedIn posts.
Output ONLY the prompt text — no quotes, no preamble, no markdown.

You are an art director for editorial photography and cinematic visuals — NOT a PowerPoint designer.

FORBIDDEN — never use these concepts or words in your prompt:
diagram, flowchart, hierarchical, organizational chart, org chart, blueprint, infographic,
nodes, icon cluster, tree structure, tiers, layers of boxes, connected icons, location icons,
process map, architecture diagram, minimalist diagram, business process diagram, network diagram,
scattered icons, lines connecting boxes, supervisor nodes, executive node

REQUIRED — every prompt must specify:
- ONE photographic or cinematic scene (or bold abstract art) — not a chart
- Medium: editorial photo, documentary film still, or fine-art abstract (pick one)
- Mood, lighting, lens (wide / 35mm / macro), color palette
- How it symbolizes the post's insight without literally listing every bullet

Rules:
- LinkedIn-professional but attention-grabbing — magazine cover energy, not clip art
- NO text, words, letters, logos, watermarks
- Landscape/wide composition
- Avoid uncanny AI faces; use silhouettes, over-shoulder, hands-only, or empty environments"""

BANNED_PROMPT_TERMS = (
    "diagram",
    "flowchart",
    "hierarchical",
    "organizational chart",
    "org chart",
    "blueprint",
    "infographic",
    " icon ",
    "icons",
    "node",
    "nodes",
    "tree structure",
    "tier",
    "tiers",
    "layers of",
    "connected by line",
    "connected by clean",
    "location icon",
    "process diagram",
    "network diagram",
    "architecture diagram",
    "minimalist diagram",
    "business process",
    "supervisor node",
    "executive node",
    "scattered",
    "org chart",
)

DRAFT_STYLE_VISUALS = {
    "provocative": (
        "Bold hook — high contrast, surprising, slightly provocative. "
        "Magazine-cover tension. Strong color accent. Make someone stop scrolling."
    ),
    "analytical": (
        "Evidence-led — investigative documentary mood. Cool tones, precise composition. "
        "Imply rigor through real objects and light — never charts or data graphics."
    ),
    "story": (
        "Personal POV — intimate documentary moment. Warm natural light, authentic workspace, "
        "human scale from behind or silhouette."
    ),
    "curious": (
        "Question-led — intriguing, slightly surreal single scene. Negative space, "
        "one unexpected detail that provokes curiosity."
    ),
    "actionable": (
        "Practical takeaway — dynamic hands-on action. Motion, tools, someone doing the work. "
        "Energetic and immediate."
    ),
    "general": (
        "Cinematic editorial metaphor — evocative, professional, never corporate clip art."
    ),
}

STYLE_APPROACHES: dict[str, tuple[str, ...]] = {
    "provocative": (
        "Dramatic split-lighting photograph — chaos on one side, order on the other — real places not icons",
        "Bold editorial still life: sand slipping through fingers on a polished boardroom table",
        "High-contrast dawn highway overpass — lone figure between two city districts",
        "Unsettling empty pharmacy aisle with one glowing warm section — cinematic wide shot",
    ),
    "analytical": (
        "Investigative documentary: over-shoulder review of real ops binders and marked maps at night",
        "Cool-toned macro of mismatched workflow printouts being aligned by hands",
        "Wide shot of five identical storefronts with subtly different lighting — real street photography",
        "Glass-walled ops room at dusk, screens glowing, no readable text — atmospheric rigor",
    ),
    "story": (
        "Warm golden-hour over-shoulder of district lead walking a pharmacy floor with staff blurred",
        "Documentary portrait from behind: manager on a regional road between two towns",
        "Intimate close-up of coffee-stained notebook beside store keys — personal practitioner detail",
        "Silhouette in doorway between back office and retail floor — human bridge moment",
    ),
    "curious": (
        "Single empty bridge at foggy dawn — mysterious scale, no people",
        "One mismatched chair in a row of identical pharmacy consultation rooms",
        "Surreal but professional: twenty identical doors, one slightly ajar with warm light",
        "Macro of two puzzle pieces that almost fit — metaphor on neutral background",
    ),
    "actionable": (
        "Hands pinning a standardized checklist in a busy clinic back office — motion blur energy",
        "Dynamic wide shot of team huddle in pharmacy stock room — candid documentary",
        "Over-shoulder coaching moment: supervisor pointing at floor plan on wall — no readable text",
        "Morning rollout: boxes being opened in sync across a bright retail back room",
    ),
    "general": (
        "Cinematic editorial photograph with natural light and shallow depth of field",
        "Moody atmospheric wide shot — dawn, rain, or golden hour negative space",
        "Close-up documentary detail — hands, tools, workspace texture",
        "Environmental metaphor — bridge, corridor, or horizon line — no icons",
    ),
}


def _is_diagram_like_prompt(prompt: str) -> bool:
    lowered = f" {prompt.lower()} "
    return any(term in lowered for term in BANNED_PROMPT_TERMS)


def _style_visual_mandate(draft_style: str) -> str:
    return DRAFT_STYLE_VISUALS.get(draft_style.strip().lower(), DRAFT_STYLE_VISUALS["general"])


def _pick_approach(draft_style: str) -> str:
    key = draft_style.strip().lower() if draft_style else "general"
    pool = STYLE_APPROACHES.get(key, STYLE_APPROACHES["general"])
    return random.choice(pool)


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
        """Use Claude to build a LinkedIn-appropriate image prompt from post text."""
        hint_block = f"\nUser's visual preference: {user_hint}" if user_hint.strip() else ""
        topic_block = f"\nTopic: {topic_name}" if topic_name else ""
        style_key = draft_style.strip().lower() or "general"
        label = draft_label.strip() or style_key.replace("_", " ").title()
        style_block = (
            f"\nDRAFT STYLE: {label} ({style_key})\n"
            f"Visual mandate: {_style_visual_mandate(style_key)}"
        )
        approach = _pick_approach(style_key)
        rejection_note = ""

        if claude_service.is_configured:
            for attempt in range(3):
                prompt = f"""Create a scroll-stopping image generation prompt for this LinkedIn draft.
{topic_block}
{style_block}

DRAFT TEXT (extract the emotional insight — do NOT illustrate it as a chart):
{draft_text[:2400]}
{hint_block}

Required scene direction: {approach}
{rejection_note}

Instructions:
- Match the draft STYLE visually — provocative drafts should feel bold; analytical drafts feel investigative
- Use ONE cinematic or editorial photograph — never diagrams, org charts, icons, or node layouts
- Symbolize consolidation/leadership through place, light, people, or metaphor — not boxes and lines
- Include: medium (photo/film still), mood, lighting, lens, palette, composition"""

                try:
                    result = claude_service.complete(
                        prompt=prompt,
                        system=LINKEDIN_IMAGE_SYSTEM,
                        model=settings.anthropic_model,
                        max_tokens=500,
                        temperature=1.0,
                    ).strip()
                    if not _is_diagram_like_prompt(result):
                        return result
                    logger.warning(
                        "Rejected diagram-like image prompt (attempt %s, style=%s)",
                        attempt + 1,
                        style_key,
                    )
                    rejection_note = (
                        "\nCRITICAL: Your last attempt used forbidden diagram/chart language. "
                        "Write a purely photographic cinematic scene with zero diagrams or icons."
                    )
                except Exception as e:
                    logger.warning(f"Claude image prompt failed, using fallback: {e}")
                    break

        return self._fallback_prompt(draft_text, user_hint, draft_style)

    async def craft_edit_prompt(
        self,
        previous_prompt: str,
        edit_instruction: str,
        draft_text: str = "",
        draft_style: str = "",
    ) -> str:
        """Revise an existing image prompt based on user feedback."""
        if claude_service.is_configured:
            style_note = _style_visual_mandate(draft_style) if draft_style else ""
            rejection_note = ""
            for attempt in range(3):
                prompt = f"""Revise this image prompt based on the user's feedback.

ORIGINAL PROMPT:
{previous_prompt}

USER REQUESTED CHANGES:
{edit_instruction}

LINKEDIN POST (for context):
{draft_text[:800]}
{f"Style mandate: {style_note}" if style_note else ""}
{rejection_note}

If the user wants an entirely new image, create a fresh photographic/cinematic prompt.
Never use diagrams, org charts, icons, nodes, or flowcharts.
Output ONLY the new prompt."""

                try:
                    result = claude_service.complete(
                        prompt=prompt,
                        system=LINKEDIN_IMAGE_SYSTEM,
                        model=settings.anthropic_model,
                        max_tokens=500,
                        temperature=0.95,
                    ).strip()
                    if not _is_diagram_like_prompt(result):
                        return result
                    rejection_note = (
                        "\nCRITICAL: Remove all diagram/chart/icon language. Use a photographic scene only."
                    )
                except Exception as e:
                    logger.warning(f"Claude edit prompt failed: {e}")
                    break

        combined = f"{previous_prompt}. Changes: {edit_instruction}"
        return combined[:900]

    def _fallback_prompt(self, draft_text: str, user_hint: str, draft_style: str = "") -> str:
        snippet = re.sub(r"\s+", " ", draft_text)[:300]
        approach = _pick_approach(draft_style or "general")
        base = (
            f"Cinematic editorial photograph for LinkedIn, {approach}. "
            f"Visual metaphor inspired by: {snippet}. "
            f"Photorealistic documentary style, dramatic natural lighting, wide landscape format, "
            f"no text, no logos, absolutely no diagrams charts icons or organizational graphics."
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
        """Generate or revise an image. Returns local URL + prompt used."""
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
