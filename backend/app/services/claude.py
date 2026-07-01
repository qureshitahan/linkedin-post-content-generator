import logging
from typing import Optional

import httpx
from anthropic import Anthropic, APIStatusError, AuthenticationError, PermissionDeniedError

from app.config import settings

logger = logging.getLogger(__name__)

PLACEHOLDER_KEY = "your_anthropic_api_key_here"
HTTP_CLIENT = httpx.Client(timeout=60.0, trust_env=False, proxy=None)


class ClaudeService:
    """Shared Anthropic client with tiered model selection."""

    def __init__(self):
        self.client = (
            Anthropic(api_key=settings.anthropic_api_key, http_client=HTTP_CLIENT)
            if settings.anthropic_api_key
            else None
        )

    @property
    def is_configured(self) -> bool:
        return bool(
            settings.anthropic_api_key
            and settings.anthropic_api_key != PLACEHOLDER_KEY
        )

    def complete(
        self,
        prompt: str,
        system: str,
        model: Optional[str] = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
    ) -> str:
        if not self.is_configured or not self.client:
            raise RuntimeError("Anthropic API key is not configured")

        try:
            response = self.client.messages.create(
                model=model or settings.anthropic_model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
        except PermissionDeniedError as e:
            raise RuntimeError(
                "Claude API access denied. Check your API key permissions and billing."
            ) from e
        except AuthenticationError as e:
            raise RuntimeError(
                "Claude API authentication failed. Check ANTHROPIC_API_KEY in .env."
            ) from e
        except APIStatusError as e:
            raise RuntimeError(f"Claude API error ({e.status_code}): {e.message}") from e

        return response.content[0].text.strip()

    def extract_text_from_image(
        self,
        content: bytes,
        media_type: str,
        filename: str = "",
    ) -> str:
        """OCR / describe an uploaded image for principle document indexing."""
        import base64

        if not self.is_configured or not self.client:
            raise RuntimeError(
                "Image parsing requires Anthropic API key (Claude vision) in .env."
            )

        b64 = base64.standard_b64encode(content).decode("ascii")
        label = f" ({filename})" if filename else ""
        prompt = (
            f"Extract ALL readable text from this image{label} for a professional background index. "
            "Include names, titles, companies, dates, skills, achievements, awards, education, "
            "certifications, and any other factual details visible. "
            "If there is no text, describe relevant professional content shown (charts, logos, "
            "project screenshots) in plain sentences. Output plain text only — no markdown."
        )

        try:
            response = self.client.messages.create(
                model=settings.anthropic_model_fast,
                max_tokens=2048,
                temperature=0.1,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": b64,
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
            )
        except APIStatusError as e:
            raise RuntimeError(f"Could not parse image: {e.message}") from e

        return response.content[0].text.strip()


claude_service = ClaudeService()
