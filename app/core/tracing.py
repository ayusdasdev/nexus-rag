"""A lightweight request trace (M9 9.1): `with span("dense_search"):` records how long a stage
took into the current request's trace.

Stdlib only, in OpenTelemetry's vocabulary (a trace of named, timed spans with attributes)
without its SDK. The request-id middleware starts one trace per request; code outside a
request records nothing. Attributes are ids, counts and sizes, never document text or prompts.
"""

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Span:
    name: str
    ms: float
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class RequestTrace:
    request_id: str | None
    spans: list[Span] = field(default_factory=list)

    def stage_ms(self) -> dict[str, float]:
        """Milliseconds per span name, summed when a stage ran more than once."""
        totals: dict[str, float] = {}
        for span_ in self.spans:
            totals[span_.name] = totals.get(span_.name, 0.0) + span_.ms
        return totals


_current: ContextVar[RequestTrace | None] = ContextVar("request_trace", default=None)


def current_trace() -> RequestTrace | None:
    return _current.get()


@contextmanager
def traced(request_id: str | None) -> Iterator[RequestTrace]:
    """A fresh trace for one request, current until the block ends."""
    trace = RequestTrace(request_id=request_id)
    token = _current.set(trace)
    try:
        yield trace
    finally:
        _current.reset(token)


def record(name: str, ms: float, **attributes: Any) -> None:
    """Add a measured stage to the current trace, if there is one."""
    trace = _current.get()
    if trace is not None:
        trace.spans.append(Span(name=name, ms=ms, attributes=attributes))
    logger.debug("span %s", name, extra={"stage": name, "ms": round(ms, 3)})


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[None]:
    """Time the block and record it, also when it raises (with the error's type only)."""
    start = time.perf_counter()
    try:
        yield
    except BaseException as exc:
        attributes["error"] = type(exc).__name__
        raise
    finally:
        record(name, (time.perf_counter() - start) * 1000.0, **attributes)
