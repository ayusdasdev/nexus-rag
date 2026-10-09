"""Opaque, signed, scope-bound pagination cursors (M7, api-audit finding 3)."""

import base64
import json
import uuid
from datetime import UTC, datetime

import pytest

from app.core.cursors import InvalidCursor, decode_cursor, encode_cursor

SCOPE = f"documents:{uuid.uuid4()}"
KEY = ["2026-10-09T12:00:00.123456+00:00", str(uuid.uuid4())]


def test_a_cursor_round_trips_within_its_scope() -> None:
    assert decode_cursor(encode_cursor(SCOPE, KEY), SCOPE) == KEY


def test_a_cursor_is_url_safe_and_does_not_show_the_scope() -> None:
    cursor = encode_cursor(SCOPE, KEY)

    assert all(c.isalnum() or c in "-_." for c in cursor)
    assert SCOPE.split(":")[1] not in cursor


def test_a_cursor_from_another_scope_is_invalid() -> None:
    # e.g. tenant A's documents cursor sent by tenant B
    other = f"documents:{uuid.uuid4()}"

    with pytest.raises(InvalidCursor):
        decode_cursor(encode_cursor(other, KEY), SCOPE)


def test_a_tampered_cursor_is_invalid() -> None:
    _payload, mac = encode_cursor(SCOPE, KEY).split(".")
    forged_key = ["2099-01-01T00:00:00+00:00", KEY[1]]
    forged = (
        base64.urlsafe_b64encode(json.dumps(forged_key).encode()).decode().rstrip("=")
    )

    with pytest.raises(InvalidCursor):
        decode_cursor(f"{forged}.{mac}", SCOPE)


@pytest.mark.parametrize(
    "garbage", ["", "x", "a.b", "...", "%%%%.%%%%", "eyJ.zzz", "a" * 5000]
)
def test_garbage_is_invalid(garbage: str) -> None:
    with pytest.raises(InvalidCursor):
        decode_cursor(garbage, SCOPE)


def test_the_signing_key_comes_from_the_jwt_secret() -> None:
    from app.core import cursors

    a = cursors._signature(
        b"payload", SCOPE, secret="one-secret-value-xxxxxxxxxxxxxxxx"
    )
    b = cursors._signature(
        b"payload", SCOPE, secret="two-secret-value-xxxxxxxxxxxxxxxx"
    )

    assert a != b


def test_datetimes_keep_microseconds_for_keyset_ordering() -> None:
    when = datetime(2026, 10, 9, 12, 0, 0, 123456, tzinfo=UTC)

    key = decode_cursor(encode_cursor(SCOPE, [when.isoformat(), KEY[1]]), SCOPE)

    assert datetime.fromisoformat(key[0]) == when
