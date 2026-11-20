from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hoshi.modules.user.models import UserAccount


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_account_by_username(self, username: str) -> UserAccount | None:
        """根据用户名查找用户账号"""

        result = (
            await self.session.execute(
                select(UserAccount).where(UserAccount.username == username)
            )
        ).scalar_one_or_none()
        return result
