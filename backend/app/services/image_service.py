"""LinkedIn post image generation — Claude crafts prompts, OpenAI GPT Image renders.

Anthropic does not generate images. We use Claude (cheap Haiku) to turn LinkedIn
post text into a professional image prompt, then OpenAI's GPT Image model to render
on demand only (when the user clicks Generate — never automatic).
"""

import base64
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


def resolve_openai_api_key() -> str:
    """Prefer process env (Azure App Settings) over pydantic-loaded settings."""
    return (os.environ.get("OPENAI_API_KEY") or settings.openai_api_key or "").strip()


def is_valid_openai_api_key(key: str) -> bool:
    normalized = key.strip().lower()
    if normalized in OPENAI_PLACEHOLDERS:
        return False
    return key.startswith("sk-")

LINKEDIN_IMAGE_SYSTEM = """You write image generation prompts for professional LinkedIn posts.
Output ONLY the prompt text — no quotes, no preamble, no markdown.

Rules for every prompt:
- Professional LinkedIn feed aesthetic: clean, credible, not stock-photo cheesy
- Must NOT look obviously AI-generated (avoid hyper-saturated, over-glossy, uncanny faces)
- Suitable for a business/professional audience
- NO text, words, letters, logos, or watermarks in the image (models render text poorly)
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
            prompt = f"""Create an image generation prompt for this specific LinkedIn draft.
{topic_block}

DRAFT TEXT TO VISUALIZE:
{draft_text[:2400]}
{hint_block}

The image must be based on THIS draft's specific hook, argument, proof point, and takeaway.
If another draft on the same topic uses a different angle, this image should still feel distinct.
Pick ONE strong visual concept (diagram, scene, or abstract representation) that supports the draft's point without literally illustrating every sentence."""

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
                    model=settings.anthropic_model_fast,
                    max_tokens=450,
                    temperature=0.7,
                )
            except Exception as e:
                logger.warning(f"Claude edit prompt failed: {e}")

        combined = f"{previous_prompt}. Changes: {edit_instruction}"
        return combined[:900]

    def _fallback_prompt(self, draft_text: str, user_hint: str) -> str:
        snippet = re.sub(r"\s+", " ", draft_text)[:400]
        base = (
            f"Professional LinkedIn post header image, clean modern style, "
            f"visually based on this draft's hook and main argument: {snippet}. "
            f"No text, no logos, landscape format, muted professional colors."
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
