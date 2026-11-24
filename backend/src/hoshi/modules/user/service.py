import logging

from fastapi.concurrency import run_in_threadpool
from pwdlib import PasswordHash
from sqlalchemy.ext.asyncio import AsyncSession

from hoshi.core.security import get_dummy_hash
from hoshi.modules.auth.constants import AuthApiCode
from hoshi.modules.auth.enums import AccountRole, AccountStatus, AccountType
from hoshi.modules.auth.schemas import AuthenticatedAccount
from hoshi.modules.user.constants import UserApiCode
from hoshi.modules.user.repository import UserRepository
from hoshi.modules.user.schemas import CurrentAccountOut
from hoshi.shared.http.exception import BusinessException

logger = logging.getLogger(__name__)
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


class AccountQueryService:
    def __init__(self, session: AsyncSession, user_repository: UserRepository) -> None:
        self.session = session
        self.user_repository = user_repository

    async def get_current_account(
        self, *, account_id: int, account_type: AccountType
    ) -> CurrentAccountOut:
        """查询并校验当前可用账号信息"""

        async with self.session.begin():
            account = await self.user_repository.find_account_by_id(account_id)
            # 校验账号是否存在、处于激活状态且类型匹配
            if (
                account is None
                or account.status != AccountStatus.ACTIVE
                or account.account_type != account_type
            ):
                actual_type = None if account is None else account.account_type
                account_status = None if account is None else account.status
                logger.warning(
                    "当前账号不可用: account_id=%s, expected_type=%s, actual_type=%s, status=%s",
                    account_id,
                    account_type,
                    actual_type,
                    account_status,
                )
                raise BusinessException(UserApiCode.ACCOUNT_UNAVAILABLE)

            current_account = CurrentAccountOut.of(account)
        return current_account
