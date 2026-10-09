"""Opaque pagination cursors: signed, and bound to the scope they were issued for (M7).

A cursor is base64url(json(key)) + "." + base64url(HMAC-SHA256(scope + payload)). The scope
(e.g. "documents:<tenant_id>") is in the MAC but not in the cursor, so a cursor can't be
edited or replayed against another tenant, user, document or conversation: any of those
fails verification, and the API answers 422.
"""

import base64
import binascii
import hashlib
import hmac
import json
from typing import Any

from app.core.config import get_settings

_MAX_LENGTH = 512


class InvalidCursor(ValueError):
    pass


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _signature(payload: bytes, scope: str, secret: str | None = None) -> bytes:
    secret = secret if secret is not None else get_settings().jwt_secret
    key = hashlib.sha256(b"nexus-cursor-v1:" + secret.encode()).digest()
    return hmac.new(key, scope.encode() + b"\x00" + payload, hashlib.sha256).digest()[
        :16
    ]


def encode_cursor(scope: str, key: list[Any]) -> str:
    payload = json.dumps(key, separators=(",", ":")).encode()
    return f"{_b64(payload)}.{_b64(_signature(payload, scope))}"


def decode_cursor(cursor: str, scope: str) -> list[Any]:
    """The key inside a cursor issued for this scope; InvalidCursor for anything else."""
    if not cursor or len(cursor) > _MAX_LENGTH or cursor.count(".") != 1:
        raise InvalidCursor("malformed cursor")
    encoded_payload, encoded_mac = cursor.split(".")
    try:
        payload, mac = _unb64(encoded_payload), _unb64(encoded_mac)
    except (binascii.Error, ValueError) as exc:
        raise InvalidCursor("malformed cursor") from exc
    if not payload or not hmac.compare_digest(mac, _signature(payload, scope)):
        raise InvalidCursor("cursor does not belong here")
    try:
        key = json.loads(payload)
    except ValueError as exc:
        raise InvalidCursor("malformed cursor") from exc
    if not isinstance(key, list):
        raise InvalidCursor("malformed cursor")
    return key
