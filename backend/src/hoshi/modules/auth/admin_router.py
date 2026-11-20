from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Response

from hoshi.api.dependencies import (
    SettingsDependency,
)
from hoshi.modules.auth.constants import AuthApiCode
from hoshi.modules.auth.cookie_utils import (
    clear_cookie,
    clear_cookie_headers,
    set_cookie,
)
from hoshi.modules.auth.dependencies import (
    get_auth_service,
    get_client_ip,
    verify_admin_origin,
)
from hoshi.modules.auth.enums import AccountType
from hoshi.modules.auth.schemas import LoginIn, LoginOut
from hoshi.modules.auth.service import AuthService
from hoshi.shared.http.exception import BusinessException
from hoshi.shared.http.response import ApiResponse

ADMIN_REFRESH_COOKIE_NAME = "hoshi_admin_refresh"
ADMIN_REFRESH_COOKIE_PATH = "/api/v1/admin/auth"


admin_router = APIRouter(prefix="/auth", tags=["管理员认证接口"])


@admin_router.post(
    "/login", dependencies=[Depends(verify_admin_origin)], summary="登录"
)
async def login(
    body: LoginIn,
    response: Response,
    settings: SettingsDependency,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> ApiResponse[LoginOut]:
    """登录"""

    tokens = await auth_service.login(
        username=body.username,
        password=body.password,
        client_ip=client_ip,
        account_type=AccountType.ADMIN,
    )
    set_cookie(
        response,
        name=ADMIN_REFRESH_COOKIE_NAME,
        value=tokens.refresh_token,
        path=ADMIN_REFRESH_COOKIE_PATH,
        max_age=settings.jwt_admin_refresh_ttl,
        secure=settings.app_env == "production",
    )
    return ApiResponse.success(
        LoginOut(access_token=tokens.access_token, expires_in=tokens.expires_in)
    )


@admin_router.post(
    "/refresh", dependencies=[Depends(verify_admin_origin)], summary="刷新访问令牌"
)
async def refresh(
    response: Response,
    settings: SettingsDependency,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    refresh_token: Annotated[
        str | None, Cookie(alias=ADMIN_REFRESH_COOKIE_NAME)
    ] = None,
) -> ApiResponse[LoginOut]:
    """刷新访问令牌"""

    try:
        tokens = await auth_service.refresh(
            refresh_token=refresh_token, account_type=AccountType.ADMIN
        )
    except BusinessException as exc:
        if exc.api_code == AuthApiCode.INVALID_TOKEN:
            headers = clear_cookie_headers(
                name=ADMIN_REFRESH_COOKIE_NAME,
                path=ADMIN_REFRESH_COOKIE_PATH,
                secure=settings.app_env == "production",
            )
            raise BusinessException(
                api_code=exc.api_code, message=exc.message, headers=headers
            ) from None
        raise

    set_cookie(
        response,
        name=ADMIN_REFRESH_COOKIE_NAME,
        value=tokens.refresh_token,
        path=ADMIN_REFRESH_COOKIE_PATH,
        max_age=settings.jwt_admin_refresh_ttl,
        secure=settings.app_env == "production",
    )
    return ApiResponse.success(
        LoginOut(access_token=tokens.access_token, expires_in=tokens.expires_in)
    )


@admin_router.post(
    "/logout", dependencies=[Depends(verify_admin_origin)], summary="登出"
)
async def logout(
    response: Response,
    settings: SettingsDependency,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    refresh_token: Annotated[
        str | None, Cookie(alias=ADMIN_REFRESH_COOKIE_NAME)
    ] = None,
) -> ApiResponse[None]:
    """登出"""

    await auth_service.logout(
        refresh_token=refresh_token, account_type=AccountType.ADMIN
    )
    clear_cookie(
        response,
        name=ADMIN_REFRESH_COOKIE_NAME,
        path=ADMIN_REFRESH_COOKIE_PATH,
        secure=settings.app_env == "production",
    )
    return ApiResponse.success()
