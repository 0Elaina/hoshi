from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager

from aiobotocore.session import get_session
from fastapi import FastAPI, Request, Response
from redis.asyncio import Redis

from hoshi.api.handlers import register_exception_handlers
from hoshi.api.v1.admin import admin_api
from hoshi.core.config import Settings
from hoshi.core.logging import configure_logging
from hoshi.db.session import create_db_engine, create_session_factory
from hoshi.infra.rabbitmq import RabbitMQFileJobPublisher
from hoshi.infra.s3 import create_s3_client
from hoshi.modules.auth.jwt import JwtService
from hoshi.modules.auth.rate_limit import LoginRateLimiter
from hoshi.modules.files.storage import FileObjectStorage

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
            async with AsyncExitStack() as stack:
                redis = await stack.enter_async_context(
                    Redis(
                        host=settings.redis_host,
                        port=settings.redis_port,
                        db=0,
                        password=password.get_secret_value() if password else None,
                        socket_connect_timeout=2.0,
                        socket_timeout=2.0,
                    )
                )
                app.state.redis = redis
                app.state.login_rate_limiter = LoginRateLimiter(redis)

                s3_settings = settings.s3_config()
                if s3_settings is not None:
                    s3_session = get_session()
                    s3_client = await stack.enter_async_context(
                        create_s3_client(
                            endpoint_url=s3_settings.endpoint_url,
                            region_name=s3_settings.region,
                            access_key=s3_settings.access_key,
                            secret_key=s3_settings.secret_key,
                            session=s3_session,
                        )
                    )
                    if s3_settings.signing_endpoint_url == s3_settings.endpoint_url:
                        s3_signing_client = s3_client
                    else:
                        s3_signing_client = await stack.enter_async_context(
                            create_s3_client(
                                endpoint_url=s3_settings.signing_endpoint_url,
                                region_name=s3_settings.region,
                                access_key=s3_settings.access_key,
                                secret_key=s3_settings.secret_key,
                                session=s3_session,
                            )
                        )
                    app.state.s3_client = s3_client
                    app.state.s3_signing_client = s3_signing_client
                    app.state.file_storage = FileObjectStorage(
                        s3_client,
                        s3_signing_client,
                        s3_settings.private_bucket,
                    )
                else:
                    app.state.s3_client = None
                    app.state.s3_signing_client = None
                    app.state.file_storage = None

                # 按配置启动非阻塞 RabbitMQ 快速唤醒发布器；未配置或暂不可用时由数据库补发接管
                rabbitmq_settings = settings.rabbitmq_config()
                if rabbitmq_settings is not None:
                    # 交由 AsyncExitStack 统一托管，应用退出时自动取消在途发布并关闭连接
                    app.state.file_job_wakeup_publisher = (
                        await stack.enter_async_context(
                            RabbitMQFileJobPublisher(
                                rabbitmq_settings,
                                app_env=settings.app_env,
                            )
                        )
                    )
                else:
                    # 未配置 Broker 时置 None，上传确认仅落库等待维护循环处理
                    app.state.file_job_wakeup_publisher = None

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
