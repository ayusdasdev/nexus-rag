"""SQL parameters never reach exception text, so logs can't carry document content
(M7 review, LOW-4)."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.repositories import document_sync_repository
from app.repositories.session import session_scope

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

SECRET = "SECRET-CHUNK-TEXT-should-not-be-logged"
# Violates the messages -> conversations foreign key, with our marker as a parameter.
INSERT = text(
    "INSERT INTO messages (id, conversation_id, tenant_id, role, content) "
    "VALUES (:id, :conversation_id, :tenant_id, 'user', :content)"
)


def _params() -> dict[str, object]:
    return {
        "id": uuid.uuid4(),
        "conversation_id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "content": SECRET,
    }


async def test_the_api_engine_hides_parameters_in_errors() -> None:
    with pytest.raises(DBAPIError) as info:
        async with session_scope() as session:
            await session.execute(INSERT, _params())

    assert SECRET not in str(info.value)


def test_the_worker_engine_hides_parameters_in_errors() -> None:
    engine = document_sync_repository._engine()  # the worker's real, cached engine
    with pytest.raises(DBAPIError) as info, engine.begin() as connection:
        connection.execute(INSERT, _params())

    assert SECRET not in str(info.value)
