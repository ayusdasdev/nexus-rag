from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str


class LLMProvider(Protocol):
    """Text in, text out. No tools, no URLs, nothing the model can act with (ADR-0007)."""

    name: str

    def stream(
        self,
        messages: Sequence[ChatMessage],
        max_tokens: int = 512,
        temperature: float = 0.0,
    ) -> AsyncIterator[str]: ...

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        max_tokens: int = 512,
        temperature: float = 0.0,
    ) -> str: ...


class FakeLLM:
    """Scripted tokens for tests. Records every call's messages."""

    name = "fake"

    def __init__(self, tokens: Sequence[str]) -> None:
        self._tokens = list(tokens)
        self.calls: list[list[ChatMessage]] = []

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        max_tokens: int = 512,
        temperature: float = 0.0,
    ) -> AsyncIterator[str]:
        self.calls.append(list(messages))
        for token in self._tokens:
            yield token

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        max_tokens: int = 512,
        temperature: float = 0.0,
    ) -> str:
        self.calls.append(list(messages))
        return "".join(self._tokens)
