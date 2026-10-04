from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.repositories.session import dispose_engine


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(title="Nexus RAG", lifespan=lifespan)
    app.include_router(health_router)
    app.include_router(auth_router)
    # Same router, mounted again under /v1 - versions the whole auth
    # surface (signup/login/me) in one place, instead of hand-picking
    # individual routes to double-decorate.
    app.include_router(auth_router, prefix="/v1")
    app.include_router(documents_router, prefix="/v1")
    return app


app = create_app()
