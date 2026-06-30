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


claude_service = ClaudeService()
