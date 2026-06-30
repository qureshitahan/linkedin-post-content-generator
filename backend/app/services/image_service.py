"""LinkedIn post image generation — Claude crafts prompts, OpenAI DALL-E renders.

Anthropic does not generate images. We use Claude (cheap Haiku) to turn LinkedIn
post text into a professional image prompt, then DALL-E 3 to render on demand only
(when the user clicks Generate — never automatic).
"""

import logging
import re
import uuid
from pathlib import Path
from typing import Optional

import httpx
from openai import OpenAI

from app.config import settings
from app.services.claude import claude_service

logger = logging.getLogger(__name__)

IMAGES_DIR = Path(__file__).resolve().parent.parent.parent / "generated_images"
OPENAI_PLACEHOLDER = "your_openai_api_key_here"

LINKEDIN_IMAGE_SYSTEM = """You write DALL-E 3 image prompts for professional LinkedIn posts.
Output ONLY the prompt text — no quotes, no preamble, no markdown.

Rules for every prompt:
- Professional LinkedIn feed aesthetic: clean, credible, not stock-photo cheesy
- Must NOT look obviously AI-generated (avoid hyper-saturated, over-glossy, uncanny faces)
- Suitable for a business/professional audience
- NO text, words, letters, logos, or watermarks in the image (DALL-E renders text poorly)
- Landscape composition (wide format)
- Can be: clean block diagram, architecture sketch, professional person at work,
  abstract concept visualization, modern office/lab scene, data flow illustration,
  minimalist infographic-style shapes (without labels)
- Formal but visually interesting — should stop the scroll without looking like an ad
- Muted, professional color palette unless the topic clearly calls for warmth
- Photorealistic OR clean illustration/diagram — pick what fits the post topic best"""


class ImageService:
    def __init__(self):
        self._client: Optional[OpenAI] = None
        if self.is_configured:
            self._client = OpenAI(api_key=settings.openai_api_key)

    @property
    def is_configured(self) -> bool:
        key = settings.openai_api_key
        return bool(key and key != OPENAI_PLACEHOLDER)

    @property
    def prompt_engine_available(self) -> bool:
        return claude_service.is_configured

    async def craft_prompt_from_draft(
        self,
        draft_text: str,
        topic_name: str = "",
        user_hint: str = "",
    ) -> str:
        """Use Claude to build a LinkedIn-appropriate DALL-E prompt from post text."""
        hint_block = f"\nUser's visual preference: {user_hint}" if user_hint.strip() else ""
        topic_block = f"\nTopic: {topic_name}" if topic_name else ""

        if claude_service.is_configured:
            prompt = f"""Create a DALL-E 3 image prompt for this LinkedIn post.
{topic_block}

POST TEXT:
{draft_text[:1200]}
{hint_block}

The image should visually support the post's main idea — not literally illustrate every sentence.
Pick ONE strong visual concept (diagram, scene, or abstract representation)."""

            try:
                return claude_service.complete(
                    prompt=prompt,
                    system=LINKEDIN_IMAGE_SYSTEM,
                    model=settings.anthropic_model_fast,
                    max_tokens=400,
                    temperature=0.7,
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
            prompt = f"""Revise this DALL-E image prompt based on the user's feedback.

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
                    model=settings.anthropic_model_fast,
                    max_tokens=450,
                    temperature=0.7,
                )
            except Exception as e:
                logger.warning(f"Claude edit prompt failed: {e}")

        combined = f"{previous_prompt}. Changes: {edit_instruction}"
        return combined[:900]

    def _fallback_prompt(self, draft_text: str, user_hint: str) -> str:
        snippet = re.sub(r"\s+", " ", draft_text)[:200]
        base = (
            f"Professional LinkedIn post header image, clean modern style, "
            f"concept related to: {snippet}. "
            f"No text, no logos, landscape format, muted professional colors."
        )
        if user_hint.strip():
            base += f" {user_hint.strip()}"
        return base[:900]

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
        if not self.is_configured or not self._client:
            raise RuntimeError(
                "OpenAI API key is not configured. Add OPENAI_API_KEY to .env for image generation."
            )

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
            response = self._client.images.generate(
                model=settings.openai_image_model,
                prompt=final_prompt,
                size=settings.openai_image_size,
                quality=settings.openai_image_quality,
                n=1,
            )
        except Exception as e:
            raise RuntimeError(f"Image generation failed: {e}") from e

        image_url = response.data[0].url
        if not image_url:
            raise RuntimeError("OpenAI returned no image URL")

        filename = await self._download_and_save(image_url)
        return {
            "image_url": f"/api/images/{filename}",
            "prompt_used": final_prompt,
            "filename": filename,
        }

    async def _download_and_save(self, url: str) -> str:
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid.uuid4().hex}.png"
        path = IMAGES_DIR / filename

        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            path.write_bytes(resp.content)

        return filename


image_service = ImageService()
