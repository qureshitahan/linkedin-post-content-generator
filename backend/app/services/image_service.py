"""LinkedIn post image generation — Claude crafts prompts, OpenAI GPT Image renders.

Anthropic does not generate images. We use Claude (cheap Haiku) to turn LinkedIn
post text into a professional image prompt, then OpenAI's GPT Image model to render
on demand only (when the user clicks Generate — never automatic).
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

Think like someone picking a cover image before posting on LinkedIn — clear, relevant, professional.
The reader should immediately see how the image connects to the post topic.

GOOD LinkedIn post images (pick ONE):
- A real workplace photo in the post's industry (pharmacy, clinic, hospital ops, boardroom, etc.)
- Someone doing the job the post describes (over-shoulder, hands-only, or from behind — avoid front-facing faces)
- A research / evidence scene: desk, laptop with blurred charts, papers, notebook, coffee — for analytical posts
- A clean hook-style graphic: bold solid background color + 1–2 simple objects that match the headline idea (no text)
- A topical before/after or side-by-side using REAL settings (e.g. chaotic vs standardized pharmacy back office)
- An operational snapshot: team huddle, site visit, district manager reviewing locations on a tablet (screen blurred)

AVOID:
- Random metaphors unrelated to the post (sand, fog, empty bridges, puzzle pieces, surreal scenes)
- Generic org charts with icon nodes, flowcharts, and scattered location icons connected by lines
- Overly dramatic cinematic shots that don't match the post subject
- Literal illustration of every sentence in the post

Rules:
- Ground every prompt in the post's industry, hook, and concrete subjects
- Professional and credible — what you'd actually see on a LinkedIn feed
- NO readable text, words, letters, logos, or watermarks
- Landscape/wide composition"""

# Only reject the org-chart / icon-cluster patterns users complained about — not all structured visuals.
ORG_CHART_PROMPT_TERMS = (
    "organizational chart",
    "org chart",
    "hierarchical diagram",
    "supervisor node",
    "executive node",
    "location icons",
    "icon cluster",
    "scattered icons",
    "connected by lines to",
    "tree structure of",
    "network diagram",
)

LINKEDIN_VISUAL_FORMATS = (
    "topic_photo — professional photo in the industry setting the post discusses",
    "workplace_scene — people working in the environment the post is about",
    "research_evidence — desk/laptop/papers suggesting data, research, or analysis",
    "hook_banner — clean bold background with simple objects illustrating the headline",
    "topical_comparison — two real-world scenes showing the contrast in the post",
    "operational_snapshot — one clear on-the-job moment the post describes",
)

DRAFT_STYLE_VISUALS = {
    "provocative": "Bold hook — strong crop, high clarity, direct topical image that matches the opening claim.",
    "analytical": "Evidence-led — research desk, data review, papers, laptop with blurred charts, clinical rigor.",
    "story": "Personal POV — authentic practitioner moment in a real workplace, warm and human.",
    "curious": "Question-led — intriguing but still topical scene that raises the post's question visually.",
    "actionable": "Practical takeaway — hands-on work, checklist, team doing the thing the post recommends.",
    "general": "Clear professional LinkedIn image directly tied to the post topic.",
}


def _is_org_chart_prompt(prompt: str) -> bool:
    lowered = prompt.lower()
    return any(term in lowered for term in ORG_CHART_PROMPT_TERMS)


def _style_visual_mandate(draft_style: str) -> str:
    return DRAFT_STYLE_VISUALS.get(draft_style.strip().lower(), DRAFT_STYLE_VISUALS["general"])


def _draft_hook(draft_text: str) -> str:
    for line in draft_text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:200]
    return draft_text[:200]


def _parse_visual_analysis(raw: str, draft_text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE)
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return {
                "industry": str(data.get("industry") or "professional business").strip(),
                "hook": str(data.get("hook") or _draft_hook(draft_text)).strip(),
                "concrete_subjects": [
                    str(s).strip() for s in (data.get("concrete_subjects") or []) if str(s).strip()
                ][:8],
                "post_theme": str(data.get("post_theme") or "").strip(),
                "recommended_format": str(data.get("recommended_format") or "topic_photo").strip(),
            }
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return {
        "industry": "professional business",
        "hook": _draft_hook(draft_text),
        "concrete_subjects": [],
        "post_theme": "",
        "recommended_format": "topic_photo",
    }


def _analyze_draft_for_visual(draft_text: str, topic_name: str, draft_style: str) -> dict:
    if not claude_service.is_configured:
        return _parse_visual_analysis("", draft_text)

    topic_block = f"\nTopic: {topic_name}" if topic_name else ""
    formats_block = "\n".join(f"- {fmt}" for fmt in LINKEDIN_VISUAL_FORMATS)
    prompt = f"""Analyze this LinkedIn draft for image planning. Return JSON only.
{topic_block}
Draft style: {draft_style or "general"}

Draft:
{draft_text[:2200]}

Choose recommended_format from:
{formats_block}

Return exactly:
{{
  "industry": "e.g. healthcare, pharmacy, fintech",
  "hook": "the opening hook or core claim in one line",
  "concrete_subjects": ["specific nouns from the post to show visually"],
  "post_theme": "one sentence on what the post is really about",
  "recommended_format": "one format key e.g. topic_photo or research_evidence"
}}"""

    try:
        raw = claude_service.complete(
            prompt=prompt,
            system="Extract visual planning facts from LinkedIn posts. Return valid JSON only.",
            model=settings.anthropic_model_fast,
            max_tokens=350,
            temperature=0.2,
        )
        return _parse_visual_analysis(raw, draft_text)
    except Exception as e:
        logger.warning(f"Visual analysis failed, using defaults: {e}")
        return _parse_visual_analysis("", draft_text)


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
        analysis = _analyze_draft_for_visual(draft_text, topic_name, style_key)
        subjects = ", ".join(analysis["concrete_subjects"]) or "key objects and settings from the post"
        rejection_note = ""

        if claude_service.is_configured:
            for attempt in range(3):
                prompt = f"""Write one image generation prompt for this LinkedIn post.
{topic_block}

POST ANALYSIS (stay faithful to this):
- Industry: {analysis['industry']}
- Hook: {analysis['hook']}
- Theme: {analysis['post_theme'] or 'See draft below'}
- Show visually: {subjects}
- Recommended format: {analysis['recommended_format']}
- Draft style ({label}): {_style_visual_mandate(style_key)}

FULL DRAFT:
{draft_text[:2200]}
{hint_block}
{rejection_note}

Instructions:
- The image must clearly relate to THIS post — a LinkedIn reader should instantly get the connection
- Use the recommended format; pick a single clear scene, not a literal bullet-by-bullet illustration
- Look like real LinkedIn content: professional, grounded, not artsy or overly dramatic
- Use real industry settings and objects from the post (pharmacy, clinic, ops desk, etc.)
- NO readable text, logos, or watermarks
- NO generic org charts with icon nodes — use real workplaces instead
- Include setting, subjects, composition, lighting, and color palette"""

                try:
                    result = claude_service.complete(
                        prompt=prompt,
                        system=LINKEDIN_IMAGE_SYSTEM,
                        model=settings.anthropic_model,
                        max_tokens=500,
                        temperature=0.85,
                    ).strip()
                    if not _is_org_chart_prompt(result):
                        return result
                    logger.warning(
                        "Rejected org-chart image prompt (attempt %s, style=%s)",
                        attempt + 1,
                        style_key,
                    )
                    rejection_note = (
                        "\nCRITICAL: Do not use org charts or icon-node diagrams. "
                        "Use a real workplace photo or research desk scene tied to the post."
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

If the user wants an entirely new image, create a fresh prompt grounded in the post topic.
Use real industry settings — not random metaphors or org-chart icons.
Output ONLY the new prompt."""

                try:
                    result = claude_service.complete(
                        prompt=prompt,
                        system=LINKEDIN_IMAGE_SYSTEM,
                        model=settings.anthropic_model,
                        max_tokens=500,
                        temperature=0.85,
                    ).strip()
                    if not _is_org_chart_prompt(result):
                        return result
                    rejection_note = (
                        "\nCRITICAL: Use a real workplace or research scene tied to the post — no org charts."
                    )
                except Exception as e:
                    logger.warning(f"Claude edit prompt failed: {e}")
                    break

        combined = f"{previous_prompt}. Changes: {edit_instruction}"
        return combined[:900]

    def _fallback_prompt(
        self,
        draft_text: str,
        user_hint: str,
        draft_style: str = "",
        analysis: Optional[dict] = None,
    ) -> str:
        info = analysis or _parse_visual_analysis("", draft_text)
        hook = info.get("hook") or _draft_hook(draft_text)
        industry = info.get("industry") or "professional business"
        subjects = ", ".join(info.get("concrete_subjects") or []) or hook
        style_note = _style_visual_mandate(draft_style or "general")
        base = (
            f"Professional LinkedIn post image for {industry}. "
            f"Clear, credible scene related to: {subjects}. "
            f"Supports the hook: {hook}. "
            f"Style: {style_note}. "
            f"Real workplace or research setting, natural lighting, landscape format, "
            f"no readable text, no logos, no org-chart icons."
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
