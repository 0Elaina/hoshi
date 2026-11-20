import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Response

from hoshi.api.dependencies import (
    SettingsDependency,
)
from hoshi.modules.auth.dependencies import (
    get_auth_service,
    get_client_ip,
    verify_admin_origin,
)
from hoshi.modules.auth.enums import AccountType
from hoshi.modules.auth.schemas import LoginIn, LoginOut
from hoshi.modules.auth.service import AuthService
from hoshi.shared.http.response import ApiResponse

ADMIN_REFRESH_COOKIE_NAME = "hoshi_admin_refresh"
ADMIN_REFRESH_COOKIE_PATH = "/api/v1/admin/auth"
logger = logging.getLogger(__name__)

admin_router = APIRouter(prefix="/auth", tags=["管理员认证接口"])


@admin_router.post(
    "/login", dependencies=[Depends(verify_admin_origin)], summary="管理员登录"
)
async def admin_login(
    body: LoginIn,
    response: Response,
    settings: SettingsDependency,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> ApiResponse[LoginOut]:
    """管理员登录"""

    tokens = await auth_service.login(
        username=body.username,
        password=body.password,
        client_ip=client_ip,
        account_type=AccountType.ADMIN,
    )
    response.set_cookie(
        key=ADMIN_REFRESH_COOKIE_NAME,
        value=tokens.refresh_token,
        max_age=settings.jwt_admin_refresh_ttl,
        path=ADMIN_REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"
    return ApiResponse.success(
        LoginOut(access_token=tokens.access_token, expires_in=tokens.expires_in)
    )
