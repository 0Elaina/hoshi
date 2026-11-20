import logging
from typing import Annotated, cast

from fastapi import Depends, Header, Request

from hoshi.api.dependencies import (
    SessionDependency,
    SettingsDependency,
    get_account_authenticator,
)
from hoshi.modules.auth.constants import AuthApiCode
from hoshi.modules.auth.jwt import JwtService
from hoshi.modules.auth.rate_limit import LoginRateLimiter
from hoshi.modules.auth.service import AccountAuthenticator, AuthService
from hoshi.shared.http.exception import BusinessException

logger = logging.getLogger(__name__)


def verify_admin_origin(
    settings: SettingsDependency,
    origin: Annotated[str | None, Header(alias="Origin")] = None,
) -> None:
    """同源校验"""

    if origin != settings.admin_origin:
        logger.warning("管理员登录来源校验失败: origin=%s", origin)
        raise BusinessException(AuthApiCode.INVALID_AUTH_ORIGIN)


def get_auth_service(
    request: Request,
    session: SessionDependency,
    settings: SettingsDependency,
    account_authenticator: Annotated[
        AccountAuthenticator, Depends(get_account_authenticator)
    ],
) -> AuthService:
    """组装 AuthService 依赖"""

    jwt_service = cast(JwtService, request.app.state.jwt_service)
    rate_limiter = cast(LoginRateLimiter, request.app.state.login_rate_limiter)
    return AuthService(
        session=session,
        settings=settings,
        jwt_service=jwt_service,
        rate_limiter=rate_limiter,
        account_authenticator=account_authenticator,
    )


def get_client_ip(request: Request) -> str:
    """获取客户端IP"""

    if request.client is None or not request.client.host:
        logger.warning("无法获取客户端IP")
        raise BusinessException(AuthApiCode.AUTH_TEMPORARILY_UNAVAILABLE)
    return request.client.host
