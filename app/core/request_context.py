"""The current request's id, for responses and every log line (M7, X-Request-ID)."""

import logging
import re
import uuid
from contextvars import ContextVar

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

# What a client may send as X-Request-ID; anything else is replaced, never echoed.
_SAFE_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")


def current_request_id() -> str | None:
    return _request_id.get()


def choose_request_id(incoming: str | None) -> str:
    """The client's id if it's safe to echo and log, otherwise a fresh one."""
    if incoming is not None and _SAFE_ID.fullmatch(incoming):
        return incoming
    return uuid.uuid4().hex


def set_request_id(value: str | None) -> object:
    return _request_id.set(value)


def reset_request_id(token: object) -> None:
    _request_id.reset(token)  # type: ignore[arg-type]


_installed = False


def install_log_record_factory() -> None:
    """Stamp every log record with request_id ("-" outside a request). Idempotent."""
    global _installed
    if _installed:
        return
    previous = logging.getLogRecordFactory()

    def factory(*args: object, **kwargs: object) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        record.request_id = _request_id.get() or "-"
        return record

    logging.setLogRecordFactory(factory)
    _installed = True
