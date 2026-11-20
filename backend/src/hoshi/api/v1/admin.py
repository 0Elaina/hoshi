from fastapi import APIRouter

from hoshi.modules.auth.admin_router import admin_router as auth_admin_router

admin_api = APIRouter(prefix="/admin")
admin_api.include_router(auth_admin_router)
