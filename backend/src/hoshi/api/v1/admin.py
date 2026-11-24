from fastapi import APIRouter, Depends

from hoshi.modules.auth.admin_router import admin_router as auth_admin_router
from hoshi.modules.auth.dependencies import require_admin_account
from hoshi.modules.user.admin_router import admin_router as user_admin_router

# 需要管理员鉴权的受保护子路由组
protected_admin_api = APIRouter(dependencies=[Depends(require_admin_account)])
protected_admin_api.include_router(user_admin_router)

# 后台管理总路由（挂载无需鉴权的认证路由 + 受保护业务路由）
admin_api = APIRouter(prefix="/admin")
admin_api.include_router(auth_admin_router)
admin_api.include_router(protected_admin_api)
