"""OpenAI API provider implementation using asynchronous REST calls."""

import json
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional
import httpx

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


class OpenAIProvider(BaseLLMProvider):
    """OpenAI Chat Completions REST provider supporting tools, JSON schema, and streaming."""

    def __init__(
        self,
        api_key: Optional[str],
        model: str = "gpt-4o-mini",
        timeout: float = 30.0,
        base_url: str = "https://api.openai.com/v1",
    ):
        super().__init__(provider_name="openai", model=model, timeout=timeout)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def _ensure_api_key(self) -> str:
        if not self.api_key or self.api_key.strip() == "":
            raise AIProviderAuthenticationError(
                message="OpenAI API key is not configured.",
                provider=self.provider_name,
                status_code=401,
            )
        return self.api_key.strip()

    def _format_messages(self, messages: List[ChatMessage]) -> List[Dict[str, Any]]:
        formatted = []
        for msg in messages:
            item: Dict[str, Any] = {"role": msg.role}
            if msg.content is not None:
                item["content"] = msg.content
            if msg.name:
                item["name"] = msg.name
            if msg.tool_call_id:
                item["tool_call_id"] = msg.tool_call_id
            if msg.tool_calls:
                item["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments) if isinstance(tc.arguments, dict) else str(tc.arguments),
                        },
                    }
                    for tc in msg.tool_calls
                ]
            formatted.append(item)
        return formatted

    def _format_tools(self, tools: Optional[List[ToolDefinition]]) -> Optional[List[Dict[str, Any]]]:
        if not tools:
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]

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
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": self._format_messages(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        formatted_tools = self._format_tools(tools)
        if formatted_tools:
            payload["tools"] = formatted_tools
            payload["tool_choice"] = "auto"

        if response_schema:
            payload["response_format"] = {"type": "json_object"}

        url = f"{self.base_url}/chat/completions"

        async def _make_request(http_client: httpx.AsyncClient) -> Dict[str, Any]:
            res = await http_client.post(url, headers=headers, json=payload)
            if res.status_code == 401:
                raise AIProviderAuthenticationError("Invalid OpenAI API key.", self.provider_name, 401)
            elif res.status_code == 429:
                raise AIProviderRateLimitError("OpenAI rate limit exceeded.", self.provider_name, 429)
            elif res.status_code >= 500:
                raise AIProviderTransientError(f"OpenAI service error ({res.status_code}).", self.provider_name, res.status_code)
            elif res.status_code != 200:
                raise AIProviderError(f"OpenAI API error: {res.text}", self.provider_name, res.status_code)
            return res.json()

        try:
            if client:
                data = await _make_request(client)
            else:
                async with httpx.AsyncClient(timeout=self.timeout) as default_client:
                    data = await _make_request(default_client)
        except httpx.TimeoutException as e:
            raise AIProviderTransientError("OpenAI request timed out.", self.provider_name) from e
        except httpx.NetworkError as e:
            raise AIProviderTransientError(f"Network error communicating with OpenAI: {e}", self.provider_name) from e
        except httpx.TimeoutException as e:
            raise AIProviderTransientError("OpenAI request timed out.", self.provider_name) from e
        except httpx.NetworkError as e:
            raise AIProviderTransientError(f"Network error communicating with OpenAI: {e}", self.provider_name) from e

        choice = data["choices"][0]
        message_data = choice["message"]
        content = message_data.get("content")
        raw_tool_calls = message_data.get("tool_calls")

        parsed_tool_calls = None
        if raw_tool_calls:
            parsed_tool_calls = []
            for tc in raw_tool_calls:
                fn = tc.get("function", {})
                args_str = fn.get("arguments", "{}")
                try:
                    args = json.loads(args_str)
                except Exception:
                    args = {"raw": args_str}
                parsed_tool_calls.append(
                    ToolCall(
                        id=tc.get("id", f"call_{fn.get('name')}"),
                        name=fn.get("name", ""),
                        arguments=args,
                    )
                )

        return LLMResponse(
            content=content,
            role="assistant",
            tool_calls=parsed_tool_calls,
            finish_reason=choice.get("finish_reason"),
            usage=data.get("usage"),
            model=data.get("model", self.model),
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
        api_key = self._ensure_api_key()
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": self._format_messages(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        url = f"{self.base_url}/chat/completions"

        client_to_use = client or httpx.AsyncClient(timeout=self.timeout)
        should_close = client is None

        try:
            async with client_to_use.stream("POST", url, headers=headers, json=payload) as response:
                if response.status_code == 401:
                    raise AIProviderAuthenticationError("Invalid OpenAI API key.", self.provider_name, 401)
                elif response.status_code == 429:
                    raise AIProviderRateLimitError("OpenAI rate limit exceeded.", self.provider_name, 429)
                elif response.status_code >= 500:
                    raise AIProviderTransientError(f"OpenAI service error ({response.status_code}).", self.provider_name, response.status_code)
                elif response.status_code != 200:
                    raise AIProviderError(f"OpenAI stream error: {response.status_code}", self.provider_name, response.status_code)

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk["choices"][0].get("delta", {})
                        text_chunk = delta.get("content")
                        if text_chunk:
                            yield text_chunk
                    except json.JSONDecodeError:
                        continue
        except httpx.TimeoutException as e:
            raise AIProviderTransientError("OpenAI stream request timed out.", self.provider_name) from e
        except httpx.NetworkError as e:
            raise AIProviderTransientError(f"Network error during OpenAI streaming: {e}", self.provider_name) from e
        finally:
            if should_close:
                await client_to_use.aclose()
