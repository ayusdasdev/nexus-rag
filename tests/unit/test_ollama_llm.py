import json
from collections.abc import Callable

import httpx
import pytest

from app.providers.llm import (
    ChatMessage,
    LLMRequestRejected,
    LLMResponseError,
    LLMUnavailable,
)
from app.providers.ollama_llm import OllamaProvider

MESSAGES = [
    ChatMessage(role="system", content="rules"),
    ChatMessage(role="user", content="question"),
]


def _ndjson(*lines: dict[str, object]) -> bytes:
    return b"".join(json.dumps(line).encode() + b"\n" for line in lines)


class _Recorder:
    def __init__(self, responses: list[Callable[[httpx.Request], httpx.Response]]):
        self._responses = responses
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._responses[len(self.requests) - 1](request)


def _provider(recorder: _Recorder, sleeps: list[float]) -> OllamaProvider:
    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    return OllamaProvider(
        base_url="http://ollama.test",
        model="llama3.2:3b",
        num_ctx=4096,
        timeout=5.0,
        transport=httpx.MockTransport(recorder),
        sleep=sleep,
    )


def _ok(*lines: dict[str, object]) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: httpx.Response(200, content=_ndjson(*lines))


def _status(code: int, body: object) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: httpx.Response(code, json=body)


async def _collect(provider: OllamaProvider) -> list[str]:
    return [token async for token in provider.stream(MESSAGES, max_tokens=64)]


@pytest.mark.asyncio
async def test_streams_message_content_and_sends_model_messages_and_options() -> None:
    recorder = _Recorder(
        [
            _ok(
                {"message": {"role": "assistant", "content": "Two "}, "done": False},
                {"message": {"role": "assistant", "content": "hours\n"}, "done": False},
                {"message": {"role": "assistant", "content": ""}, "done": True},
            )
        ]
    )
    sleeps: list[float] = []

    tokens = await _collect(_provider(recorder, sleeps))

    assert tokens == ["Two ", "hours\n"]
    request = recorder.requests[0]
    assert request.method == "POST"
    assert request.url == "http://ollama.test/api/chat"
    body = json.loads(request.content)
    assert body["model"] == "llama3.2:3b"
    assert body["stream"] is True
    assert body["messages"] == [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "question"},
    ]
    assert body["options"] == {"temperature": 0.0, "num_predict": 64, "num_ctx": 4096}
    assert sleeps == []


@pytest.mark.asyncio
async def test_complete_joins_the_stream() -> None:
    recorder = _Recorder(
        [
            _ok(
                {"message": {"content": "a"}},
                {"message": {"content": "b"}, "done": True},
            )
        ]
    )

    assert await _provider(recorder, []).complete(MESSAGES) == "ab"


@pytest.mark.asyncio
async def test_an_error_line_in_the_stream_is_a_response_error() -> None:
    recorder = _Recorder(
        [_ok({"message": {"content": "a"}}, {"error": "out of memory"})]
    )

    with pytest.raises(LLMResponseError, match="out of memory"):
        await _collect(_provider(recorder, []))


@pytest.mark.asyncio
async def test_a_stream_that_ends_before_done_is_a_response_error() -> None:
    recorder = _Recorder([_ok({"message": {"content": "a"}, "done": False})])

    with pytest.raises(LLMResponseError, match="ended"):
        await _collect(_provider(recorder, []))


@pytest.mark.asyncio
async def test_a_missing_model_is_rejected_with_a_pull_hint_and_not_retried() -> None:
    recorder = _Recorder([_status(404, {"error": "model 'llama3.2:3b' not found"})])
    sleeps: list[float] = []

    with pytest.raises(LLMRequestRejected, match="ollama pull llama3.2:3b") as info:
        await _collect(_provider(recorder, sleeps))

    assert info.value.status == 404
    assert len(recorder.requests) == 1
    assert sleeps == []


@pytest.mark.asyncio
async def test_a_5xx_is_retried_once_then_succeeds() -> None:
    recorder = _Recorder(
        [
            _status(503, {"error": "loading"}),
            _ok({"message": {"content": "ok"}, "done": True}),
        ]
    )
    sleeps: list[float] = []

    assert await _collect(_provider(recorder, sleeps)) == ["ok"]
    assert len(recorder.requests) == 2
    assert sleeps == [1.0]


@pytest.mark.asyncio
async def test_a_5xx_twice_is_unavailable_after_exactly_one_retry() -> None:
    recorder = _Recorder(
        [_status(500, {"error": "boom"}), _status(500, {"error": "boom"})]
    )

    with pytest.raises(LLMUnavailable) as info:
        await _collect(_provider(recorder, []))

    assert info.value.status == 500
    assert len(recorder.requests) == 2


@pytest.mark.asyncio
async def test_a_connection_failure_is_unavailable() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(LLMUnavailable, match="Ollama"):
        await _collect(_provider(_Recorder([refuse]), []))
