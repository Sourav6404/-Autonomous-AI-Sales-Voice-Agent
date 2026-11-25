"""Factory for resolving and instantiating configured AI providers."""

from typing import Optional
from backend.app.ai.providers.base import BaseLLMProvider
from backend.app.ai.providers.gemini_provider import GeminiProvider
from backend.app.ai.providers.openai_provider import OpenAIProvider
from backend.app.core.config import settings


def get_ai_provider(provider_name: Optional[str] = None) -> BaseLLMProvider:
    """Instantiates and returns the configured AI LLM provider."""
    name = (provider_name or settings.DEFAULT_AI_PROVIDER).lower().strip()

    if name == "gemini":
        return GeminiProvider(
            api_key=settings.GEMINI_API_KEY,
            model=settings.GEMINI_MODEL,
            timeout=settings.AI_REQUEST_TIMEOUT_SECONDS,
        )
    elif name == "openai":
        return OpenAIProvider(
            api_key=settings.OPENAI_API_KEY,
            model=settings.OPENAI_MODEL,
            timeout=settings.AI_REQUEST_TIMEOUT_SECONDS,
        )
    else:
        raise ValueError(f"Unsupported AI provider: '{name}'. Choose 'openai' or 'gemini'.")
