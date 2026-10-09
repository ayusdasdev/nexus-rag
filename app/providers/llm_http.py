"""HTTP plumbing shared by the Ollama and Anthropic providers: one retry, typed errors."""

import json
import math
from collections.abc import AsyncIterator, Awaitable, Callable

import httpx

from app.providers.llm import (
    LLMRateLimited,
    LLMRequestRejected,
    LLMUnavailable,
)

Sleep = Callable[[float], Awaitable[None]]

# A server asking for a longer wait than this gets a typed error instead of a stalled answer.
MAX_RETRY_DELAY = 10.0


def _retry_after(response: httpx.Response) -> float | None:
    """Seconds the server asked us to wait; None unless finite and non-negative."""
    try:
        value = float(response.headers["retry-after"])
    except (KeyError, ValueError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def _detail(body: bytes) -> str:
    """The provider's own error text: Anthropic {"error": {type, message}}, Ollama
    {"error": "..."}. Request headers (and so the API key) never appear here."""
    try:
        data = json.loads(body)
    except ValueError:
        return body[:200].decode("utf-8", "replace")
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        return f"{error.get('type', 'error')}: {error.get('message', '')}"
    if isinstance(error, str):
        return error
    return body[:200].decode("utf-8", "replace")


async def open_stream(
    client: httpx.AsyncClient,
    request: httpx.Request,
    *,
    service: str,
    sleep: Sleep,
    retry_delay: float,
) -> httpx.Response:
    """Send request and return the open streaming response.

    429 and 5xx are retried exactly once, after retry-after (capped) or retry_delay. Any
    other 4xx is never retried. The caller must close the returned response.
    """
    for attempt in (1, 2):
        try:
            response = await client.send(request, stream=True)
        except httpx.TimeoutException as exc:
            raise LLMUnavailable(f"{service} timed out") from exc
        except httpx.TransportError as exc:
            raise LLMUnavailable(
                f"{service} is unreachable ({type(exc).__name__})"
            ) from exc

        status = response.status_code
        if status < 400:
            return response
        body = await response.aread()
        await response.aclose()
        retry_after = _retry_after(response)
        if (status == 429 or status >= 500) and attempt == 1:
            delay = retry_after if retry_after is not None else retry_delay
            await sleep(min(delay, MAX_RETRY_DELAY))
            continue

        message = f"{service} returned {status}: {_detail(body)}"
        if status == 429:
            raise LLMRateLimited(message, status, retry_after)
        if status >= 500:
            raise LLMUnavailable(message, status)
        raise LLMRequestRejected(message, status)
    raise AssertionError("unreachable")


async def lines(response: httpx.Response, *, service: str) -> AsyncIterator[str]:
    """Response lines, with transport failures mid-stream mapped to LLMUnavailable."""
    try:
        async for line in response.aiter_lines():
            yield line
    except httpx.TimeoutException as exc:
        raise LLMUnavailable(f"{service} timed out mid-stream") from exc
    except httpx.TransportError as exc:
        raise LLMUnavailable(f"{service} stream broke ({type(exc).__name__})") from exc
