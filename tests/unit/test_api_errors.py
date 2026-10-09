"""Shared HTTPException instances grow their traceback on every raise (M6 review, MEDIUM-1).

Each raise must use a fresh exception, so repeated 404s/401s can't pin request data.
"""

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.api import conversations, deps


def _depth(exc: BaseException) -> int:
    depth, tb = 0, exc.__traceback__
    while tb is not None:
        depth, tb = depth + 1, tb.tb_next
    return depth


def test_each_conversation_404_is_a_fresh_exception_with_the_same_body() -> None:
    first, second = conversations.not_found(), conversations.not_found()

    assert first is not second
    assert (first.status_code, first.detail) == (second.status_code, second.detail)
    assert (first.status_code, first.detail) == (404, "Conversation not found")


@pytest.mark.asyncio
async def test_repeated_bad_tokens_do_not_grow_one_exceptions_traceback() -> None:
    bad = HTTPAuthorizationCredentials(scheme="Bearer", credentials="not-a-jwt")
    depths = []
    for _ in range(5):
        with pytest.raises(HTTPException) as info:
            await deps.get_current_user(bad)
        assert info.value.status_code == 401
        depths.append(_depth(info.value))

    assert len(set(depths)) == 1
