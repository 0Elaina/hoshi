from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hoshi.modules.auth.models import AuthSession


class AuthSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self, *, sid: str, account_id: int, refresh_jti: str, expires_at: datetime
    ) -> AuthSession:
        """新增会话"""

        auth_session = AuthSession(
            id=sid,
            account_id=account_id,
            refresh_jti=refresh_jti,
            expires_at=expires_at,
        )
        self.session.add(auth_session)
        await self.session.flush()
        return auth_session

    async def get_by_id_for_update(self, sid: str) -> AuthSession | None:
        """获取认证会话并加锁"""

        result = (
            await self.session.execute(
                select(AuthSession).where(AuthSession.id == sid).with_for_update()
            )
        ).scalar_one_or_none()
        return result

    async def rotate(
        self, auth_session: AuthSession, *, refresh_jti: str, now: datetime
    ) -> None:
        """轮换刷新会话"""

        auth_session.refresh_jti = refresh_jti
        auth_session.updated_at = now
        await self.session.flush()

    async def revoke(self, auth_session: AuthSession, *, now: datetime) -> None:
        """撤销会话"""

        auth_session.revoked_at = now
        auth_session.updated_at = now
        await self.session.flush()
