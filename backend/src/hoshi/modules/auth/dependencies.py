import logging
from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import Annotated, cast

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from hoshi.api.dependencies import (
    SessionDependency,
    SettingsDependency,
    get_account_authenticator,
)
from hoshi.modules.auth.constants import AuthApiCode
from hoshi.modules.auth.enums import AccountType
from hoshi.modules.auth.jwt import JwtService
from hoshi.modules.auth.rate_limit import LoginRateLimiter
from hoshi.modules.auth.schemas import AccessTokenPayload
from hoshi.modules.auth.service import AccountAuthenticator, AuthService
from hoshi.shared.http.exception import BusinessException

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False, bearerFormat="JWT")


def verify_admin_origin(
    settings: SettingsDependency,
    origin: Annotated[str | None, Header(alias="Origin")] = None,
) -> None:
    """同源校验"""

    if origin != settings.admin_origin:
        logger.warning("管理员登录来源校验失败: origin=%s", origin)
        raise BusinessException(AuthApiCode.INVALID_AUTH_ORIGIN)


def get_jwt_service(request: Request) -> JwtService:
    """从 app.state 获取 JwtService 实例"""
    return cast(JwtService, request.app.state.jwt_service)


def get_auth_service(
    request: Request,
    session: SessionDependency,
    settings: SettingsDependency,
    account_authenticator: Annotated[
        AccountAuthenticator, Depends(get_account_authenticator)
    ],
    jwt_service: Annotated[JwtService, Depends(get_jwt_service)],
) -> AuthService:
    """组装 AuthService 依赖"""

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


async def get_access_identity(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)
    ],
    jwt_service: Annotated[JwtService, Depends(get_jwt_service)],
) -> AccessTokenPayload:
    """提取并校验 Bearer Access Token, 返回当前请求的用户身份载荷"""
    if credentials is None:
        raise BusinessException(
            AuthApiCode.INVALID_TOKEN, headers={"WWW-Authenticate": "Bearer"}
        )
    try:
        return jwt_service.verify_access(credentials.credentials)
    except BusinessException as exc:
        # 令牌无效时补充 WWW-Authenticate 响应头以符合 Bearer 规范
        if exc.api_code == AuthApiCode.INVALID_TOKEN:
            raise BusinessException(
                exc.api_code,
                exc.message,
                headers={"WWW-Authenticate": "Bearer"},
            ) from None
        raise


type AccessIdentityDependency = Annotated[
    AccessTokenPayload, Depends(get_access_identity)
]


# 缓存生成的依赖函数实例，避免多处路由引用时重复创建导致 FastAPI 依赖缓存失效
@lru_cache
def require_account_type(
    expected_type: AccountType,
) -> Callable[[AccessIdentityDependency], Awaitable[AccessTokenPayload]]:
    """生成校验账号类型的 FastAPI 依赖函数工厂"""

    async def _require_account_type(
        identity: AccessIdentityDependency,
    ) -> AccessTokenPayload:
        if identity.account_type != expected_type:
            logger.warning(
                "账号类型无权访问当前入口: account_id=%s, expected=%s, actual=%s",
                identity.account_id,
                expected_type.value,
                identity.account_type.value,
            )
            raise BusinessException(AuthApiCode.ACCESS_DENIED)
        return identity

    return _require_account_type


require_admin_account = require_account_type(AccountType.ADMIN)
type AdminAccountDependency = Annotated[
    AccessTokenPayload, Depends(require_admin_account)
]
require_user_account = require_account_type(AccountType.USER)
type UserAccountDependency = Annotated[
    AccessTokenPayload, Depends(require_user_account)
]
