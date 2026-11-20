import logging
from datetime import timedelta
from typing import Protocol
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from hoshi.core.config import Settings
from hoshi.modules.auth.constants import AuthApiCode
from hoshi.modules.auth.enums import AccountType
from hoshi.modules.auth.jwt import JwtService
from hoshi.modules.auth.rate_limit import LoginRateLimiter
from hoshi.modules.auth.repository import AuthSessionRepository
from hoshi.modules.auth.schemas import AuthenticatedAccount, IssuedTokens
from hoshi.shared.http.exception import BusinessException
from hoshi.shared.utils.time_utils import utc_now

logger = logging.getLogger(__name__)


class AccountAuthenticator(Protocol):
    async def authenticate(
        self, username: str, password: str
    ) -> AuthenticatedAccount: ...

    async def get_active_account(
        self, account_id: int
    ) -> AuthenticatedAccount | None: ...


class AuthService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        settings: Settings,
        jwt_service: JwtService,
        rate_limiter: LoginRateLimiter,
        account_authenticator: AccountAuthenticator,
    ) -> None:
        self.session = session
        self.settings = settings
        self.jwt_service = jwt_service
        self.rate_limiter = rate_limiter
        self.account_authenticator = account_authenticator
        self.auth_session_repository = AuthSessionRepository(session)

    async def login(
        self, *, username: str, password: str, client_ip: str, account_type: AccountType
    ) -> IssuedTokens:
        """账号登录"""

        # 限流
        await self.rate_limiter.check_login(
            account_type=account_type, client_ip=client_ip, username=username
        )

        async with self.session.begin():
            try:
                authenticated_account = await self.account_authenticator.authenticate(
                    username, password
                )
            except BusinessException as exc:
                logger.info(
                    "登录失败: %s (%s), %s", username, client_ip, exc.api_code.code
                )
                raise exc from None

            if authenticated_account.account_type != account_type:
                logger.info(
                    "登录账号类型不匹配: %s (%s), expected=%s, actual=%s",
                    username,
                    client_ip,
                    account_type.value,
                    authenticated_account.account_type.value,
                )
                raise BusinessException(AuthApiCode.INVALID_CREDENTIALS)

            now = utc_now()
            sid = str(uuid4())
            refresh_jti = str(uuid4())
            refresh_ttl = (
                self.settings.jwt_admin_refresh_ttl
                if account_type == AccountType.ADMIN
                else self.settings.jwt_user_refresh_ttl
            )
            refresh_expires_at = now + timedelta(seconds=refresh_ttl)

            await self.auth_session_repository.create(
                sid=sid,
                account_id=authenticated_account.id,
                refresh_jti=refresh_jti,
                expires_at=refresh_expires_at,
            )
            tokens = self.jwt_service.issue_tokens(
                authenticated_account,
                sid=sid,
                refresh_jti=refresh_jti,
                now=now,
                refresh_expires_at=refresh_expires_at,
            )
        logger.info("用户 %s 登录成功", username)
        return tokens
