"""Unit tests for AI Provider abstractions, OpenAI, Gemini, and Factory resolution."""

import pytest
from backend.app.ai.providers.base import (
    AIProviderAuthenticationError,
    AIProviderError,
    AIProviderRateLimitError,
    AIProviderTransientError,
    BaseLLMProvider,
    ChatMessage,
    LLMResponse,
    ToolCall,
    ToolDefinition,
)
from backend.app.ai.providers.factory import get_ai_provider
from backend.app.ai.providers.gemini_provider import GeminiProvider
from backend.app.ai.providers.openai_provider import OpenAIProvider


class MockLLMProvider(BaseLLMProvider):
    """Deterministic mock provider for unit and orchestration testing."""

    def __init__(self, responses=None):
        super().__init__(provider_name="mock", model="mock-model")
        self.responses = responses or ["Hello, how may I assist you today?"]
        self.call_count = 0
        self.received_messages = []

    async def generate_response(
        self,
        messages,
        tools=None,
        response_schema=None,
        temperature=0.7,
        max_tokens=1024,
    ) -> LLMResponse:
        self.received_messages.append(messages)
        idx = min(self.call_count, len(self.responses) - 1)
        resp = self.responses[idx]
        self.call_count += 1

        if isinstance(resp, LLMResponse):
            return resp
        return LLMResponse(
            content=str(resp),
            role="assistant",
            provider="mock",
            model="mock-model",
        )

    async def generate_stream(self, messages, tools=None, temperature=0.7, max_tokens=1024):
        resp = await self.generate_response(messages, tools, None, temperature, max_tokens)
        if resp.content:
            for word in resp.content.split():
                yield f"{word} "


def test_provider_factory_resolution():
    """Tests resolving configured providers from settings."""
    openai_p = get_ai_provider("openai")
    assert isinstance(openai_p, OpenAIProvider)
    assert openai_p.provider_name == "openai"

    gemini_p = get_ai_provider("gemini")
    assert isinstance(gemini_p, GeminiProvider)
    assert gemini_p.provider_name == "gemini"

    with pytest.raises(ValueError, match="Unsupported AI provider"):
        get_ai_provider("anthropic_unsupported")


@pytest.mark.asyncio
async def test_missing_api_key_raises_auth_error():
    """Verifies that invoking providers without an API key raises AIProviderAuthenticationError."""
    openai_no_key = OpenAIProvider(api_key=None)
    with pytest.raises(AIProviderAuthenticationError, match="OpenAI API key is not configured"):
        await openai_no_key.generate_response([ChatMessage(role="user", content="Hi")])

    gemini_no_key = GeminiProvider(api_key="")
    with pytest.raises(AIProviderAuthenticationError, match="Google Gemini API key is not configured"):
        await gemini_no_key.generate_response([ChatMessage(role="user", content="Hi")])


@pytest.mark.asyncio
async def test_mock_provider_streaming():
    """Verifies streaming interface contract across provider base."""
    mock = MockLLMProvider(["Welcome to FortiSales AI receptionist."])
    chunks = []
    async for chunk in mock.generate_stream([ChatMessage(role="user", content="Hello")]):
        chunks.append(chunk)

    full_text = "".join(chunks).strip()
    assert full_text == "Welcome to FortiSales AI receptionist."
