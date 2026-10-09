import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.providers.anthropic_llm import AnthropicProvider
from app.providers.llm import (
    ChatMessage,
    LLMNotConfigured,
    LLMRateLimited,
    LLMRefused,
    LLMRequestRejected,
    LLMResponseError,
    LLMUnavailable,
)

KEY = "sk-ant-test-key-never-real"
MESSAGES = [
    ChatMessage(role="system", content="rules"),
    ChatMessage(role="user", content="question"),
]


def _sse(*events: tuple[str, dict[str, Any]]) -> bytes:
    return b"".join(
        f"event: {name}\ndata: {json.dumps(data)}\n\n".encode() for name, data in events
    )


def _delta(text: str) -> tuple[str, dict[str, Any]]:
    return (
        "content_block_delta",
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": text},
        },
    )


START = ("message_start", {"type": "message_start", "message": {"id": "msg_1"}})
PING = ("ping", {"type": "ping"})
THINKING = (
    "content_block_delta",
    {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "thinking_delta", "thinking": ""},
    },
)
END_TURN = (
    "message_delta",
    {
        "type": "message_delta",
        "delta": {"stop_reason": "end_turn"},
        "usage": {"output_tokens": 3},
    },
)
STOP = ("message_stop", {"type": "message_stop"})


class _Recorder:
    def __init__(self, responses: list[Callable[[httpx.Request], httpx.Response]]):
        self._responses = responses
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._responses[len(self.requests) - 1](request)


def _ok(
    *events: tuple[str, dict[str, Any]],
) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: httpx.Response(
        200, content=_sse(*events), headers={"content-type": "text/event-stream"}
    )


def _error(
    code: int, kind: str, headers: dict[str, str] | None = None
) -> Callable[[httpx.Request], httpx.Response]:
    body = {"type": "error", "error": {"type": kind, "message": f"{kind} happened"}}
    return lambda request: httpx.Response(code, json=body, headers=headers or {})


def _provider(recorder: _Recorder, sleeps: list[float]) -> AnthropicProvider:
    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    return AnthropicProvider(
        api_key=KEY,
        model="claude-opus-5-5",
        base_url="https://anthropic.test",
        effort="medium",
        min_max_tokens=16000,
        timeout=5.0,
        transport=httpx.MockTransport(recorder),
        sleep=sleep,
    )


async def _collect(provider: AnthropicProvider) -> list[str]:
    return [token async for token in provider.stream(MESSAGES, max_tokens=512)]


def test_an_empty_api_key_is_not_configured() -> None:
    with pytest.raises(LLMNotConfigured):
        AnthropicProvider(
            api_key="",
            model="claude-opus-5-5",
            base_url="https://anthropic.test",
            effort="medium",
            min_max_tokens=16000,
            timeout=5.0,
        )


@pytest.mark.asyncio
async def test_streams_text_deltas_and_sends_the_messages_api_request() -> None:
    recorder = _Recorder(
        [_ok(START, PING, THINKING, _delta("Two "), _delta("hours."), END_TURN, STOP)]
    )

    tokens = await _collect(_provider(recorder, []))

    assert tokens == ["Two ", "hours."]
    request = recorder.requests[0]
    assert request.url == "https://anthropic.test/v1/messages"
    assert request.headers["x-api-key"] == KEY
    assert request.headers["anthropic-version"] == "2023-06-01"
    assert request.headers["anthropic-beta"] == "server-side-fallback-2026-07-01"
    body = json.loads(request.content)
    assert body == {
        "model": "claude-opus-5-5",
        # Thinking counts toward max_tokens, so a small answer budget is raised.
        "max_tokens": 16000,
        "stream": True,
        "system": "rules",
        "messages": [{"role": "user", "content": "question"}],
        "output_config": {"effort": "medium"},
        "fallbacks": "default",
    }
    # Opus 5.5 rejects sampling parameters.
    assert "temperature" not in body


@pytest.mark.asyncio
async def test_a_429_waits_for_retry_after_and_retries_once() -> None:
    recorder = _Recorder(
        [_error(429, "rate_limit_error", {"retry-after": "2"}), _ok(_delta("ok"), STOP)]
    )
    sleeps: list[float] = []

    assert await _collect(_provider(recorder, sleeps)) == ["ok"]
    assert sleeps == [2.0]
    assert len(recorder.requests) == 2


@pytest.mark.asyncio
async def test_a_huge_retry_after_is_capped() -> None:
    recorder = _Recorder(
        [_error(429, "rate_limit_error", {"retry-after": "600"}), _ok(STOP)]
    )
    sleeps: list[float] = []

    await _collect(_provider(recorder, sleeps))

    assert sleeps == [10.0]


@pytest.mark.asyncio
async def test_a_429_twice_is_rate_limited_with_retry_after() -> None:
    recorder = _Recorder(
        [
            _error(429, "rate_limit_error", {"retry-after": "3"}),
            _error(429, "rate_limit_error", {"retry-after": "3"}),
        ]
    )

    with pytest.raises(LLMRateLimited) as info:
        await _collect(_provider(recorder, []))

    assert info.value.status == 429
    assert info.value.retry_after == 3.0
    assert len(recorder.requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("code,kind", [(500, "api_error"), (529, "overloaded_error")])
async def test_a_5xx_twice_is_unavailable(code: int, kind: str) -> None:
    recorder = _Recorder([_error(code, kind), _error(code, kind)])

    with pytest.raises(LLMUnavailable, match=kind) as info:
        await _collect(_provider(recorder, []))

    assert info.value.status == code
    assert len(recorder.requests) == 2


@pytest.mark.asyncio
async def test_a_400_is_rejected_without_retry_and_never_echoes_the_key() -> None:
    recorder = _Recorder([_error(400, "invalid_request_error")])
    sleeps: list[float] = []

    with pytest.raises(LLMRequestRejected, match="invalid_request_error") as info:
        await _collect(_provider(recorder, sleeps))

    assert info.value.status == 400
    assert KEY not in str(info.value)
    assert len(recorder.requests) == 1
    assert sleeps == []


@pytest.mark.asyncio
async def test_an_error_event_mid_stream_is_typed_and_not_retried() -> None:
    overloaded = (
        "error",
        {"type": "error", "error": {"type": "overloaded_error", "message": "busy"}},
    )
    recorder = _Recorder([_ok(START, _delta("Two "), overloaded)])

    tokens: list[str] = []
    with pytest.raises(LLMUnavailable, match="overloaded_error"):
        async for token in _provider(recorder, []).stream(MESSAGES):
            tokens.append(token)

    assert tokens == ["Two "]
    assert len(recorder.requests) == 1


@pytest.mark.asyncio
async def test_a_refusal_stop_reason_raises_refused() -> None:
    refusal = (
        "message_delta",
        {"type": "message_delta", "delta": {"stop_reason": "refusal"}},
    )
    recorder = _Recorder([_ok(START, refusal, STOP)])

    with pytest.raises(LLMRefused):
        await _collect(_provider(recorder, []))


@pytest.mark.asyncio
async def test_a_stream_without_message_stop_is_a_response_error() -> None:
    recorder = _Recorder([_ok(START, _delta("Two "))])

    with pytest.raises(LLMResponseError, match="ended"):
        await _collect(_provider(recorder, []))


@pytest.mark.asyncio
async def test_a_connection_failure_is_unavailable() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(LLMUnavailable, match="Anthropic"):
        await _collect(_provider(_Recorder([refuse]), []))
