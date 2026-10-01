from sqlalchemy import text

from app.repositories.session import session_scope


async def ping_db() -> None:
    """Run a trivial query to confirm the database connection is alive."""
    async with session_scope() as session:
        await session.execute(text("SELECT 1"))
