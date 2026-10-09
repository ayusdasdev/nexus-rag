"""Cursor pages for list endpoints (M7): parse `after`, build `next_cursor`."""

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, Query, status

from app.core.cursors import InvalidCursor, decode_cursor, encode_cursor

# No max_length here: decode_cursor caps the length, so every bad cursor gets the same
# "Invalid cursor" problem.
AFTER = Query(
    default=None,
    description="The `next_cursor` of the previous page. Opaque, and only valid for the "
    "same list it came from.",
)


def _invalid() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid cursor"
    )


def time_key(after: str | None, scope: str) -> tuple[datetime, UUID] | None:
    """(created_at, id) from a cursor, or None for the first page; 422 if invalid."""
    if after is None:
        return None
    try:
        created_at, row_id = decode_cursor(after, scope)
        return datetime.fromisoformat(created_at), UUID(row_id)
    except (InvalidCursor, TypeError, ValueError) as exc:
        raise _invalid() from exc


def index_key(after: str | None, scope: str) -> int | None:
    """chunk_index from a cursor, or None for the first page; 422 if invalid."""
    if after is None:
        return None
    try:
        (index,) = decode_cursor(after, scope)
        if not isinstance(index, int):
            raise TypeError("chunk index must be an int")
        return index
    except (InvalidCursor, TypeError, ValueError) as exc:
        raise _invalid() from exc


def page[T](
    rows: Sequence[T], limit: int, scope: str, key: Callable[[T], list[Any]]
) -> tuple[list[T], str | None]:
    """rows were fetched with limit + 1: return this page and the cursor for the next."""
    items = list(rows[:limit])
    if len(rows) <= limit or not items:
        return items, None
    return items, encode_cursor(scope, key(items[-1]))


def time_cursor_key(created_at: datetime, row_id: UUID) -> list[Any]:
    return [created_at.isoformat(), str(row_id)]
