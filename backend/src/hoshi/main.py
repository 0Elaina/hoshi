from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis

from hoshi.api.handlers import register_exception_handlers
from hoshi.api.v1.admin import admin_api
from hoshi.core.config import Settings
from hoshi.core.logging import configure_logging
from hoshi.db.session import create_db_engine, create_session_factory
from hoshi.modules.auth.jwt import JwtService
from hoshi.modules.auth.rate_limit import LoginRateLimiter


def create_app() -> FastAPI:
    settings = Settings()  # pyright: ignore
    configure_logging(settings)
    jwt_service = JwtService(settings)
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
                socket_connect_timeout=2.0,
                socket_timeout=2.0,
            ) as redis:
                app.state.redis = redis
                app.state.login_rate_limiter = LoginRateLimiter(redis)
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
    app.state.settings = settings
    app.state.jwt_service = jwt_service
    app.include_router(admin_api, prefix="/api/v1")
    return app
