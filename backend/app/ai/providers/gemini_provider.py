"""Google Gemini API provider implementation using asynchronous REST calls."""

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional
import httpx

from backend.app.core.config import settings
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

logger = logging.getLogger(__name__)


class GeminiProvider(BaseLLMProvider):
    """Google Gemini REST provider supporting function calling, JSON schema, and streaming."""

    def __init__(
        self,
        api_key: Optional[str],
        model: str = "gemini-1.5-flash",
        timeout: float = 30.0,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
    ):
        super().__init__(provider_name="gemini", model=model, timeout=timeout)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._shared_client: Optional[httpx.AsyncClient] = None

    def _get_shared_client(self) -> httpx.AsyncClient:
        if self._shared_client is None or self._shared_client.is_closed:
            self._shared_client = httpx.AsyncClient(
                timeout=self.timeout,
                verify=False,
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
        return self._shared_client

    def _ensure_api_key(self) -> str:
        if not self.api_key or self.api_key.strip() == "":
            raise AIProviderAuthenticationError(
                message="Google Gemini API key is not configured.",
                provider=self.provider_name,
                status_code=401,
            )
        return self.api_key.strip()

    def _format_contents(self, messages: List[ChatMessage]) -> tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
        system_instruction = None
        contents = []

        for msg in messages:
            if msg.role == "system":
                system_instruction = {"parts": [{"text": msg.content or ""}]}
            elif msg.role == "user":
                contents.append({"role": "user", "parts": [{"text": msg.content or ""}]})
            elif msg.role == "assistant":
                parts: List[Dict[str, Any]] = []
                if msg.content:
                    parts.append({"text": msg.content})
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        call_dict: Dict[str, Any] = {
                            "name": tc.name,
                            "args": tc.arguments,
                        }
                        if tc.id and not tc.id.startswith("call_"):
                            call_dict["id"] = tc.id
                        part_dict: Dict[str, Any] = {"functionCall": call_dict}
                        if tc.thought_signature:
                            part_dict["thoughtSignature"] = tc.thought_signature
                        parts.append(part_dict)
                contents.append({"role": "model", "parts": parts})
            elif msg.role == "tool":
                # Function response for Gemini (must have role: "user")
                contents.append({
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": msg.name or "tool_result",
                                "response": {"result": msg.content},
                            }
                        }
                    ],
                })

        return system_instruction, contents

    def _format_tools(self, tools: Optional[List[ToolDefinition]]) -> Optional[List[Dict[str, Any]]]:
        if not tools:
            return None
        declarations = []
        for t in tools:
            declarations.append({
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            })
        return [{"functionDeclarations": declarations}]

    async def generate_response(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[ToolDefinition]] = None,
        response_schema: Optional[Dict[str, Any]] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        client: Optional[httpx.AsyncClient] = None,
    ) -> LLMResponse:
        api_key = self._ensure_api_key()
        system_instruction, contents = self._format_contents(messages)

        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }

        if system_instruction:
            payload["systemInstruction"] = system_instruction

        formatted_tools = self._format_tools(tools)
        if formatted_tools:
            payload["tools"] = formatted_tools

        if response_schema:
            payload["generationConfig"]["responseMimeType"] = "application/json"

        clean_model = self.model.removeprefix("models/")
        url = f"{self.base_url}/models/{clean_model}:generateContent?key={api_key}"

        async def _make_request(http_client: httpx.AsyncClient) -> Dict[str, Any]:
            max_attempts = 5
            for attempt in range(max_attempts):
                res = await http_client.post(url, json=payload)
                if res.status_code in (429, 502, 503, 504) and attempt < max_attempts - 1:
                    delay = min(1.5 * (2 ** attempt), 6.0)
                    logger.warning(
                        "Gemini %s on attempt %s. Retrying in %ss... Details: %s",
                        res.status_code, attempt + 1, delay, res.text[:200]
                    )
                    await asyncio.sleep(delay)
                    continue

                if res.status_code == 400 and "API_KEY_INVALID" in res.text:
                    raise AIProviderAuthenticationError("Invalid Gemini API key.", self.provider_name, 401)
                elif res.status_code == 429:
                    raise AIProviderRateLimitError("Gemini rate limit exceeded.", self.provider_name, 429)
                elif res.status_code >= 500:
                    raise AIProviderTransientError(f"Gemini service error ({res.status_code}).", self.provider_name, res.status_code)
                elif res.status_code != 200:
                    raise AIProviderError(f"Gemini API error: {res.text}", self.provider_name, res.status_code)
                return res.json()

        try:
            active_client = client or self._get_shared_client()
            data = await _make_request(active_client)
        except httpx.TimeoutException as e:
            raise AIProviderTransientError("Gemini request timed out.", self.provider_name) from e
        except httpx.NetworkError as e:
            raise AIProviderTransientError(f"Network error communicating with Gemini: {e}", self.provider_name) from e

        candidates = data.get("candidates", [])
        if not candidates:
            return LLMResponse(content="", role="assistant", provider=self.provider_name)

        first_candidate = candidates[0]
        content_parts = first_candidate.get("content", {}).get("parts", [])

        text_content = ""
        parsed_tool_calls: Optional[List[ToolCall]] = None

        for part in content_parts:
            if "text" in part:
                text_content += part["text"]
            elif "functionCall" in part:
                if parsed_tool_calls is None:
                    parsed_tool_calls = []
                fc = part["functionCall"]
                thought_sig = part.get("thoughtSignature") or fc.get("thought_signature") or part.get("thought_signature")
                parsed_tool_calls.append(
                    ToolCall(
                        id=fc.get("id") or f"call_{fc.get('name')}",
                        name=fc.get("name", ""),
                        arguments=fc.get("args", {}),
                        thought_signature=thought_sig,
                    )
                )

        finish_reason = first_candidate.get("finishReason")
        usage_metadata = data.get("usageMetadata", {})
        usage_dict = {
            "prompt_tokens": int(usage_metadata.get("promptTokenCount", 0)),
            "completion_tokens": int(usage_metadata.get("candidatesTokenCount", 0)),
            "total_tokens": int(usage_metadata.get("totalTokenCount", 0)),
        }

        return LLMResponse(
            content=text_content if text_content else None,
            role="assistant",
            tool_calls=parsed_tool_calls,
            finish_reason=finish_reason,
            usage=usage_dict,
            model=self.model,
            provider=self.provider_name,
        )

    async def generate_stream(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[ToolDefinition]] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        client: Optional[httpx.AsyncClient] = None,
    ) -> AsyncGenerator[str, None]:
        """Streams response tokens from Google Gemini using SSE streamGenerateContent."""
        api_key = self._ensure_api_key()
        system_instruction, contents = self._format_contents(messages)

        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }

        if system_instruction:
            payload["systemInstruction"] = system_instruction

        formatted_tools = self._format_tools(tools)
        if formatted_tools:
            payload["tools"] = formatted_tools

        clean_model = self.model.removeprefix("models/")
        url = f"{self.base_url}/models/{clean_model}:streamGenerateContent?alt=sse&key={api_key}"

        client_to_use = client or httpx.AsyncClient(timeout=self.timeout, verify=False)
        should_close = client is None

        try:
            async with client_to_use.stream("POST", url, json=payload) as response:
                if response.status_code == 400 and "API_KEY_INVALID" in (await response.aread()).decode(errors="ignore"):
                    raise AIProviderAuthenticationError("Invalid Gemini API key.", self.provider_name, 401)
                elif response.status_code == 429:
                    raise AIProviderRateLimitError("Gemini rate limit exceeded.", self.provider_name, 429)
                elif response.status_code >= 500:
                    raise AIProviderTransientError(f"Gemini service error ({response.status_code}).", self.provider_name, response.status_code)
                elif response.status_code != 200:
                    raise AIProviderError(f"Gemini stream error: {response.status_code}", self.provider_name, response.status_code)

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    try:
                        chunk = json.loads(data_str)
                        candidates = chunk.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            for p in parts:
                                text_val = p.get("text")
                                if text_val:
                                    yield text_val
                    except json.JSONDecodeError:
                        continue
        except httpx.TimeoutException as e:
            raise AIProviderTransientError("Gemini stream request timed out.", self.provider_name) from e
        except httpx.NetworkError as e:
            raise AIProviderTransientError(f"Network error during Gemini streaming: {e}", self.provider_name) from e
        finally:
            if should_close:
                await client_to_use.aclose()
