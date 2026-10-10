from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

# hide_parameters: a DB error message never carries chunk text or other values into logs.
_engine = create_async_engine(
    get_settings().database_url, pool_pre_ping=True, hide_parameters=True
)
_session_factory = async_sessionmaker(_engine, expire_on_commit=False)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    async with _session_factory() as session:
        yield session


async def dispose_engine() -> None:
    await _engine.dispose()
