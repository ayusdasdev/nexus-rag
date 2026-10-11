"""JSON structured logs (M9 9.1): one JSON object per line with request_id and tenant_id.

Logs carry ids, sizes and timings, never document text or prompts. An exception is logged by
its type and stack frames (file, line, function) only: exception messages can echo prompt or
document fragments (the same rule as the chat error logs).
"""

import json
import logging
import sys
import traceback
from datetime import UTC, datetime
from typing import Any

from app.core.request_context import current_request_id, current_tenant_id

# Extra fields a log call may attach (logger.info(..., extra={...})). Anything else is
# dropped, so a stray extra can't put document text into the logs.
EXTRA_FIELDS = (
    "stage",
    "ms",
    "event",
    "status_code",
    "count",
    "model",
    "document_id",
    "conversation_id",
    "message_id",
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        request_id = getattr(record, "request_id", None)
        if request_id in (None, "-"):
            request_id = current_request_id()
        tenant_id = getattr(record, "tenant_id", None) or current_tenant_id()
        line: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id,
            "tenant_id": str(tenant_id) if tenant_id is not None else None,
        }
        for field in EXTRA_FIELDS:
            if field in record.__dict__:
                line[field] = record.__dict__[field]
        if record.exc_info and record.exc_info[0] is not None:
            line["exc_type"] = record.exc_info[0].__name__
            # file:line in function per frame; no source lines, which can quote literals.
            line["stack"] = [
                f"{frame.filename}:{frame.lineno} in {frame.name}"
                for frame in traceback.extract_tb(record.exc_info[2])
            ]
        return json.dumps(line, default=str)


_configured = False


def configure_logging(level: str = "info") -> None:
    """JSON lines on stderr for the root logger and uvicorn's loggers. Idempotent."""
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        server_logger = logging.getLogger(name)
        server_logger.handlers = [handler]
        server_logger.propagate = False
    _configured = True
