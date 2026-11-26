from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from redis.asyncio import Redis

from hoshi.api.handlers import register_exception_handlers
from hoshi.api.v1.admin import admin_api
from hoshi.core.config import Settings
from hoshi.core.logging import configure_logging
from hoshi.db.session import create_db_engine, create_session_factory
from hoshi.infra.object_storage import S3ObjectStorage, open_s3_client
from hoshi.modules.auth.jwt import JwtService
from hoshi.modules.auth.rate_limit import LoginRateLimiter

AUTH_NO_STORE_PREFIXS = ("/api/v1/admin/auth", "/api/v1/auth/")


async def add_auth_no_store(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """为认证接口响应统一设置 Cache-Control: no-store"""
    response = await call_next(request)
    if request.url.path.startswith(AUTH_NO_STORE_PREFIXS):
        response.headers["Cache-Control"] = "no-store"
    return response


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
            async with (
                Redis(
                    host=settings.redis_host,
                    port=settings.redis_port,
                    db=0,
                    password=password.get_secret_value() if password else None,
                    socket_connect_timeout=2.0,
                    socket_timeout=2.0,
                ) as redis,
                open_s3_client(settings) as s3_client,
            ):
                app.state.redis = redis
                app.state.login_rate_limiter = LoginRateLimiter(redis)
                app.state.object_storage = S3ObjectStorage(
                    s3_client, settings.s3_bucket
                )
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

    app.middleware("http")(add_auth_no_store)

    app.state.settings = settings
    app.state.jwt_service = jwt_service
    app.include_router(admin_api, prefix="/api/v1")
    return app
