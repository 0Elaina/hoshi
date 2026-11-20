from fastapi.concurrency import run_in_threadpool
from pwdlib import PasswordHash
from sqlalchemy.ext.asyncio import AsyncSession

from hoshi.core.security import get_dummy_hash
from hoshi.modules.auth.constants import AuthApiCode
from hoshi.modules.auth.enums import AccountRole, AccountStatus, AccountType
from hoshi.modules.auth.schemas import AuthenticatedAccount
from hoshi.modules.user.repository import UserRepository
from hoshi.shared.http.exception import BusinessException

_DUMMY_HASH = get_dummy_hash()


class AccountAuthenticateService:
    def __init__(
        self,
        session: AsyncSession,
        password_encoder: PasswordHash,
        user_repository: UserRepository,
    ) -> None:
        self.session = session
        self.password_encoder = password_encoder
        self.user_repository = user_repository

    async def authenticate(self, username: str, password: str) -> AuthenticatedAccount:
        """认证账号"""

        account = await self.user_repository.find_account_by_username(username)
        if account is None:
            _ = await run_in_threadpool(
                self.password_encoder.verify, password, _DUMMY_HASH
            )
            raise BusinessException(AuthApiCode.INVALID_CREDENTIALS)

        if not await run_in_threadpool(
            self.password_encoder.verify, password, account.password_hash
        ):
            raise BusinessException(AuthApiCode.INVALID_CREDENTIALS)

        if account.status != AccountStatus.ACTIVE:
            raise BusinessException(AuthApiCode.INVALID_CREDENTIALS)
        return AuthenticatedAccount(
            id=account.id,
            role=AccountRole(account.role),
            account_type=AccountType(account.account_type),
        )

    async def get_active_account(self, account_id: int) -> AuthenticatedAccount | None:
        """查询可用的账号"""

        account = await self.user_repository.find_account_by_id(account_id)
        if account is None or AccountStatus.ACTIVE != account.status:
            # 不抛错, 交给调用方处理 (撤销会话)
            return None
        return AuthenticatedAccount(
            id=account_id,
            role=AccountRole(account.role),
            account_type=AccountType(account.account_type),
        )
