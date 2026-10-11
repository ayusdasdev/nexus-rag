"""X-Request-ID middleware: choose an id, expose it to logs, echo it, and turn an unhandled
exception into a 500 problem with that id and no stack trace (M7)."""

import json
import logging

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.problems import PROBLEM_JSON, problem_body
from app.core.request_context import (
    choose_request_id,
    reset_request_id,
    reset_tenant_id,
    set_request_id,
    set_tenant_id,
)

logger = logging.getLogger(__name__)

HEADER = b"x-request-id"


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = next((v for k, v in scope["headers"] if k == HEADER), None)
        try:
            decoded = incoming.decode("ascii") if incoming is not None else None
        except UnicodeDecodeError:
            decoded = None
        request_id = choose_request_id(decoded)
        token = set_request_id(request_id)
        tenant_token = set_tenant_id(None)
        started = False

        async def send_with_id(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                headers = [(k, v) for k, v in message.get("headers", []) if k != HEADER]
                message = {
                    **message,
                    "headers": [*headers, (HEADER, request_id.encode())],
                }
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception as exc:
            logger.exception("unhandled %s", type(exc).__name__)
            if started:
                raise  # a stream already began; nothing clean can be sent now
            body = json.dumps(problem_body(500, "Internal server error")).encode()
            await send_with_id(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [
                        (b"content-type", PROBLEM_JSON.encode()),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send_with_id({"type": "http.response.body", "body": body})
        finally:
            reset_tenant_id(tenant_token)
            reset_request_id(token)
