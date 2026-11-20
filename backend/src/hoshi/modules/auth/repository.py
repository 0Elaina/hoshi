from datetime import datetime

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
