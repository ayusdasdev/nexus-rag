import inspect

import pytest

from app.providers.llm import ChatMessage, FakeLLM, LLMProvider

MESSAGES = [
    ChatMessage(role="system", content="s"),
    ChatMessage(role="user", content="u"),
]


@pytest.mark.asyncio
async def test_fake_llm_streams_its_scripted_tokens_and_records_the_call() -> None:
    llm = FakeLLM(["Two ", "hours\n", "[1]."])

    tokens = [token async for token in llm.stream(MESSAGES)]

    assert tokens == ["Two ", "hours\n", "[1]."]
    assert llm.calls == [MESSAGES]


@pytest.mark.asyncio
async def test_fake_llm_complete_joins_its_tokens() -> None:
    llm = FakeLLM(["a", "b"])

    assert await llm.complete(MESSAGES) == "ab"
    assert llm.calls == [MESSAGES]


def test_the_provider_interface_has_no_tool_or_url_parameters() -> None:
    # ADR-0007 layer 2: the model gets text in and text out, nothing it can act with.
    for method in (LLMProvider.stream, LLMProvider.complete):
        params = set(inspect.signature(method).parameters)
        assert params == {"self", "messages", "max_tokens", "temperature"}
