from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str


class LLMError(Exception):
    """Base for every provider failure. status is the HTTP status when there was one."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class LLMNotConfigured(LLMError):
    """The selected provider can't be built, e.g. no API key. Never retried."""


class LLMUnavailable(LLMError):
    """Unreachable, timed out, or 5xx/overloaded after the one retry."""


class LLMRateLimited(LLMError):
    """429 after the one retry."""

    def __init__(
        self, message: str, status: int | None = None, retry_after: float | None = None
    ) -> None:
        super().__init__(message, status)
        self.retry_after = retry_after


class LLMRequestRejected(LLMError):
    """A 4xx other than 429: the request itself is wrong. Never retried."""


class LLMResponseError(LLMError):
    """The stream was malformed, reported an error, or ended early."""


class LLMRefused(LLMError):
    """The model (and any fallback) declined to answer."""


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
