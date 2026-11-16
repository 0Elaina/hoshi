from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis

from hoshi.api.handlers import register_exception_handlers
from hoshi.core.config import Settings
from hoshi.db.session import create_db_engine, create_session_factory


def create_app() -> FastAPI:
    settings = Settings()
    development = settings.app_env == "development"

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_db_engine(settings.database_url())
        try:
            app.state.session_factory = create_session_factory(engine)
            password = settings.redis_password
            async with Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                db=0,
                password=password.get_secret_value() if password else None,
            ) as redis:
                app.state.redis = redis
                yield
        finally:
            await engine.dispose()

    app = FastAPI(
        title="Hoshi",
        lifespan=lifespan,
        docs_url="/api/docs" if development else None,
        openapi_url="/api/openapi.json" if development else None,
        redoc_url=None,
        swagger_ui_oauth2_redirect_url=None,
    )
    register_exception_handlers(app)
    return app
