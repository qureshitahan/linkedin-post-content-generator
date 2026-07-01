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

LINKEDIN_IMAGE_SYSTEM = """You write vivid, creative image generation prompts for professional LinkedIn posts.
Output ONLY the prompt text — no quotes, no preamble, no markdown.

Your job is scroll-stopping visual storytelling — NOT generic corporate clip art.

AVOID (these produce boring, repetitive images):
- Flowcharts, process diagrams, before/after icon layouts
- Scattered icons connected by lines and nodes
- Flat minimalist business diagrams or infographic-style shapes
- Literal illustrations of every bullet point in the post
- Generic "corporate strategy documentation" or PowerPoint aesthetics

PREFER (pick ONE approach — vary across generations):
- Editorial photography: candid professional moment, dramatic natural light, real environment
- Cinematic metaphor: one powerful scene symbolizing the post's tension or insight
- Environmental storytelling: bridge, corridor, command center, dawn light, scale contrast
- Hands-on detail: close-up of work in progress without faces front-and-center
- Abstract art direction: bold color, texture, motion, negative space — still credible for LinkedIn
- Documentary wide shot: show cohesion or fragmentation through place and light, not icon clusters

Rules:
- Professional LinkedIn audience — credible, not cheesy stock photo
- NO text, words, letters, logos, watermarks (models render text poorly)
- Landscape/wide composition
- One clear focal concept — evocative, not exhaustive
- Specify mood, lighting, color palette, camera angle, and artistic medium
- Avoid uncanny AI faces; prefer silhouettes, over-shoulder, hands-only, or empty environments"""

VISUAL_APPROACHES = (
    "Editorial photograph with natural light and shallow depth of field",
    "Cinematic wide shot using environment as metaphor",
    "Close-up documentary detail — hands, tools, workspace texture",
    "Architectural composition — corridors, bridges, skylines, scale contrast",
    "Moody atmospheric scene — dawn, rain, golden hour, negative space",
    "Abstract professional art — texture, gradient, geometric tension without icons",
    "Over-the-shoulder workplace moment — authentic, not posed stock",
    "Environmental portrait of a multi-site operation — shown through place, not diagrams",
)


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
    ) -> str:
        """Use Claude to build a LinkedIn-appropriate image prompt from post text."""
        hint_block = f"\nUser's visual preference: {user_hint}" if user_hint.strip() else ""
        topic_block = f"\nTopic: {topic_name}" if topic_name else ""

        if claude_service.is_configured:
            approach = random.choice(VISUAL_APPROACHES)
            prompt = f"""Create a creative image generation prompt for this specific LinkedIn draft.
{topic_block}

DRAFT TEXT TO VISUALIZE:
{draft_text[:2400]}
{hint_block}

Required visual approach for THIS image: {approach}

Instructions:
- Translate the post's core insight into a metaphorical or cinematic scene — not a literal diagram
- Do NOT use flowcharts, icon clusters, before/after layouts, or process diagrams
- Pick ONE strong visual concept that would stop someone scrolling on LinkedIn
- Include specific art direction: mood, lighting, palette, camera angle, medium (photo vs illustration)
- If the post mentions consolidation, leadership, or operations — show it through environment,
  human scale, or metaphor (e.g. a lone figure on a bridge between two districts) rather than icons"""

            try:
                return claude_service.complete(
                    prompt=prompt,
                    system=LINKEDIN_IMAGE_SYSTEM,
                    model=settings.anthropic_model,
                    max_tokens=500,
                    temperature=0.95,
                )
            except Exception as e:
                logger.warning(f"Claude image prompt failed, using fallback: {e}")

        return self._fallback_prompt(draft_text, user_hint)

    async def craft_edit_prompt(
        self,
        previous_prompt: str,
        edit_instruction: str,
        draft_text: str = "",
    ) -> str:
        """Revise an existing image prompt based on user feedback."""
        if claude_service.is_configured:
            prompt = f"""Revise this image prompt based on the user's feedback.

ORIGINAL PROMPT:
{previous_prompt}

USER REQUESTED CHANGES:
{edit_instruction}

LINKEDIN POST (for context):
{draft_text[:800]}

If the user wants an entirely new image, create a fresh prompt inspired by the post and their notes.
If they want specific edits, incorporate those changes while keeping it LinkedIn-professional.
Output ONLY the new prompt."""

            try:
                return claude_service.complete(
                    prompt=prompt,
                    system=LINKEDIN_IMAGE_SYSTEM,
                    model=settings.anthropic_model,
                    max_tokens=500,
                    temperature=0.9,
                )
            except Exception as e:
                logger.warning(f"Claude edit prompt failed: {e}")

        combined = f"{previous_prompt}. Changes: {edit_instruction}"
        return combined[:900]

    def _fallback_prompt(self, draft_text: str, user_hint: str) -> str:
        snippet = re.sub(r"\s+", " ", draft_text)[:400]
        approach = random.choice(VISUAL_APPROACHES)
        base = (
            f"Cinematic LinkedIn header image, {approach.lower()}. "
            f"Evocative visual metaphor for this post's main idea: {snippet}. "
            f"No text, no logos, no flowcharts or icon diagrams, landscape format, "
            f"dramatic lighting, professional editorial quality."
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
        user_hint: str = "",
    ) -> dict:
        """Generate or revise an image. Returns local URL + prompt used."""
        client = self._get_client()

        if mode == "edit" and (previous_prompt or edit_instruction):
            final_prompt = await self.craft_edit_prompt(
                previous_prompt=previous_prompt or user_hint,
                edit_instruction=edit_instruction or user_hint,
                draft_text=draft_text,
            )
        elif user_hint.strip() and not previous_prompt:
            final_prompt = await self.craft_prompt_from_draft(
                draft_text=draft_text,
                topic_name=topic_name,
                user_hint=user_hint,
            )
        elif prompt.strip():
            final_prompt = prompt.strip()
        else:
            final_prompt = await self.craft_prompt_from_draft(
                draft_text=draft_text,
                topic_name=topic_name,
                user_hint=user_hint,
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
