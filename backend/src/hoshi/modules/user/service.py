from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

import hoshi.modules.user.repository as user_repository
from hoshi.modules.auth.api_code import AuthApiCode
from hoshi.modules.auth.enums import AccountRole, AccountStatus, AccountType
from hoshi.modules.auth.schemas import AuthenticatedAccount
from hoshi.modules.auth.service import PASSWORD_HASH
from hoshi.shared.http.exception import BusinessException

_DUMMY_HASH = PASSWORD_HASH.hash("dummy")


async def authenticate(
    session: AsyncSession, username: str, password: str
) -> AuthenticatedAccount:
    """认证账号"""

    account = await user_repository.find_account_by_username(session, username)
    if account is None:
        _ = await run_in_threadpool(PASSWORD_HASH.verify, password, _DUMMY_HASH)
        raise BusinessException(AuthApiCode.INVALID_CREDENTIALS)

    if not await run_in_threadpool(
        PASSWORD_HASH.verify, password, account.password_hash
    ):
        raise BusinessException(AuthApiCode.INVALID_CREDENTIALS)

    if account.status != AccountStatus.ACTIVE:
        raise BusinessException(AuthApiCode.INVALID_CREDENTIALS)
    return AuthenticatedAccount(
        id=account.id,
        role=AccountRole(account.role),
        account_type=AccountType(account.account_type),
    )
