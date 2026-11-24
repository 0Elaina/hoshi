from typing import Annotated

from fastapi import APIRouter, Depends, Response

from hoshi.modules.auth.dependencies import AdminAccountDependency
from hoshi.modules.auth.enums import AccountType
from hoshi.modules.user.dependencies import get_account_query_service
from hoshi.modules.user.schemas import CurrentAccountOut
from hoshi.modules.user.service import AccountQueryService
from hoshi.shared.http.response import ApiResponse

admin_router = APIRouter(prefix="/accounts", tags=["管理员账号接口"])


@admin_router.get("/me", summary="获取当前账号信息")
async def get_me(
    response: Response,
    identity: AdminAccountDependency,
    account_query_service: Annotated[
        AccountQueryService, Depends(get_account_query_service)
    ],
) -> ApiResponse[CurrentAccountOut]:
    """获取当前登录管理员的账号详情"""

    account = await account_query_service.get_current_account(
        account_id=identity.account_id, account_type=AccountType.ADMIN
    )
    # 禁止客户端或中间代理缓存敏感的个人账号信息
    response.headers["Cache-Control"] = "no-store"
    return ApiResponse.success(account)
