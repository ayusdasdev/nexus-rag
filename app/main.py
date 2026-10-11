from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.conversations import router as conversations_router
from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.api.openapi import install_openapi, operation_id
from app.api.problems import install_problem_handlers
from app.api.request_id import RequestIdMiddleware
from app.api.search import router as search_router
from app.api.traces import router as traces_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.request_context import install_log_record_factory
from app.repositories.session import dispose_engine


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    install_log_record_factory()
    configure_logging(get_settings().log_level)
    app = FastAPI(
        title="Nexus RAG",
        version="0.1.0",
        lifespan=lifespan,
        generate_unique_id_function=operation_id,
    )
    install_problem_handlers(app)
    app.include_router(health_router)
    # Auth lives only under /v1 (the unversioned mount was removed in M7).
    app.include_router(auth_router, prefix="/v1")
    app.include_router(documents_router, prefix="/v1")
    app.include_router(search_router, prefix="/v1")
    app.include_router(chat_router, prefix="/v1")
    app.include_router(conversations_router, prefix="/v1")
    app.include_router(traces_router, prefix="/v1")
    install_openapi(app)
    # Added last, so it is the outermost middleware and sees every error.
    app.add_middleware(RequestIdMiddleware)
    return app


app = create_app()
