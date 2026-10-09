import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from typing import Any

import httpx

from app.core.config import Effort
from app.providers.llm import (
    ChatMessage,
    LLMNotConfigured,
    LLMRateLimited,
    LLMRefused,
    LLMResponseError,
    LLMUnavailable,
)
from app.providers.llm_http import Sleep, lines, open_stream

_SERVICE = "Anthropic"
API_VERSION = "2023-06-01"
# Server-side refusal fallback, routed by refusal category ("fallbacks": "default").
FALLBACK_BETA = "server-side-fallback-2026-07-01"


async def _events(response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
    """Parse Server-Sent Events into their JSON data payloads."""
    data: list[str] = []
    async for line in lines(response, service=_SERVICE):
        if line == "":
            if data:
                try:
                    event = json.loads("\n".join(data))
                except ValueError as exc:
                    raise LLMResponseError(
                        "Anthropic sent an event that isn't JSON"
                    ) from exc
                data = []
                if isinstance(event, dict):
                    yield event
            continue
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
        # "event:" names repeat the payload's "type"; comments (":") are keep-alives.


def _stream_error(event: dict[str, Any]) -> Exception:
    error = event.get("error") or {}
    kind = str(error.get("type", "error"))
    message = f"Anthropic stream error {kind}: {error.get('message', '')}"
    if kind == "rate_limit_error":
        return LLMRateLimited(message)
    if kind in ("overloaded_error", "api_error"):
        return LLMUnavailable(message)
    return LLMResponseError(message)


class AnthropicProvider:
    """Claude Messages API over httpx, streaming (no SDK, decision B).

    Built only with a non-empty API key. Thinking is always on for the default model and
    counts toward max_tokens, so a small answer budget is raised to min_max_tokens.
    Sampling parameters are rejected by the model, so temperature is never sent.
    """

    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        effort: Effort,
        min_max_tokens: int,
        timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
        retry_delay: float = 1.0,
    ) -> None:
        if not api_key:
            raise LLMNotConfigured("ANTHROPIC_API_KEY is not set")
        self.model = model
        self._api_key = api_key
        self._base_url = base_url
        self._effort = effort
        self._min_max_tokens = min_max_tokens
        self._timeout = timeout
        self._transport = transport
        self._sleep = sleep
        self._retry_delay = retry_delay

    def __repr__(self) -> str:
        return f"AnthropicProvider(model={self.model!r})"

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        max_tokens: int = 512,
        temperature: float = 0.0,
    ) -> AsyncGenerator[str, None]:
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max(max_tokens, self._min_max_tokens),
            "stream": True,
            "system": "\n\n".join(m.content for m in messages if m.role == "system"),
            "messages": [
                {"role": m.role, "content": m.content}
                for m in messages
                if m.role != "system"
            ],
            "output_config": {"effort": self._effort},
            "fallbacks": "default",
        }
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": API_VERSION,
            "anthropic-beta": FALLBACK_BETA,
        }
        async with httpx.AsyncClient(
            base_url=self._base_url, timeout=self._timeout, transport=self._transport
        ) as client:
            request = client.build_request(
                "POST", "/v1/messages", json=body, headers=headers
            )
            response = await open_stream(
                client,
                request,
                service=_SERVICE,
                sleep=self._sleep,
                retry_delay=self._retry_delay,
            )
            try:
                async for event in _events(response):
                    kind = event.get("type")
                    if kind == "content_block_delta":
                        delta = event.get("delta") or {}
                        if delta.get("type") == "text_delta" and delta.get("text"):
                            yield str(delta["text"])
                    elif kind == "message_delta":
                        stop = (event.get("delta") or {}).get("stop_reason")
                        if stop == "refusal":
                            raise LLMRefused("Claude declined to answer")
                    elif kind == "error":
                        raise _stream_error(event)
                    elif kind == "message_stop":
                        return
                raise LLMResponseError("Anthropic stream ended before message_stop")
            finally:
                await response.aclose()

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        max_tokens: int = 512,
        temperature: float = 0.0,
    ) -> str:
        return "".join(
            [token async for token in self.stream(messages, max_tokens, temperature)]
        )
