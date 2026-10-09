import asyncio
import json
from collections.abc import AsyncIterator, Sequence

import httpx

from app.providers.llm import ChatMessage, LLMRequestRejected, LLMResponseError
from app.providers.llm_http import Sleep, lines, open_stream

_SERVICE = "Ollama"


class OllamaProvider:
    """Local Ollama over its HTTP API (POST /api/chat, streaming NDJSON)."""

    name = "ollama"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        num_ctx: int,
        timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
        retry_delay: float = 1.0,
    ) -> None:
        self.model = model
        self._base_url = base_url
        self._num_ctx = num_ctx
        self._timeout = timeout
        self._transport = transport
        self._sleep = sleep
        self._retry_delay = retry_delay

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        max_tokens: int = 512,
        temperature: float = 0.0,
    ) -> AsyncIterator[str]:
        body = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": self._num_ctx,
            },
        }
        async with httpx.AsyncClient(
            base_url=self._base_url, timeout=self._timeout, transport=self._transport
        ) as client:
            request = client.build_request("POST", "/api/chat", json=body)
            try:
                response = await open_stream(
                    client,
                    request,
                    service=_SERVICE,
                    sleep=self._sleep,
                    retry_delay=self._retry_delay,
                )
            except LLMRequestRejected as exc:
                if exc.status == 404:
                    raise LLMRequestRejected(
                        f"{exc} - run `ollama pull {self.model}`", exc.status
                    ) from exc
                raise
            try:
                async for line in lines(response, service=_SERVICE):
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except ValueError as exc:
                        raise LLMResponseError(
                            "Ollama sent a line that isn't JSON"
                        ) from exc
                    if "error" in data:
                        raise LLMResponseError(f"Ollama error: {data['error']}")
                    content = data.get("message", {}).get("content", "")
                    if content:
                        yield content
                    if data.get("done"):
                        return
                raise LLMResponseError("Ollama stream ended before done")
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
