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
from hoshi.modules.auth.schemas import (
    AuthenticatedAccount,
    IssuedTokens,
    RefreshTokenPayload,
)
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
                logger.warning(
                    "登录失败: %s (%s), %s", username, client_ip, exc.api_code.code
                )
                raise exc from None

            if authenticated_account.account_type != account_type:
                logger.warning(
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

    async def refresh(
        self, *, refresh_token: str | None, account_type: AccountType
    ) -> IssuedTokens:
        """刷新会话"""

        if not refresh_token:
            logger.warning(
                "刷新会话失败: 缺少刷新令牌, account_type=%s", account_type.value
            )
            raise BusinessException(AuthApiCode.INVALID_TOKEN)

        try:
            payload = self.jwt_service.verify_refresh(refresh_token)
        except BusinessException as exc:
            logger.warning(
                "刷新令牌验签失败: account_type=%s, code=%s",
                account_type.value,
                exc.api_code.code,
            )
            raise

        if payload.account_type != account_type:
            logger.warning(
                "刷新令牌账号类型不匹配: sid=%s, expected=%s, actual=%s",
                payload.sid,
                account_type.value,
                payload.account_type.value,
            )
            raise BusinessException(AuthApiCode.INVALID_TOKEN)

        # 轮换会话
        async with self.session.begin():
            tokens = await self._rotate_session(
                payload=payload, account_type=account_type
            )

        if tokens is None:
            raise BusinessException(AuthApiCode.INVALID_TOKEN)
        return tokens

    async def logout(
        self, *, refresh_token: str | None, account_type: AccountType
    ) -> None:
        """登出"""
        if not refresh_token:
            logger.debug("刷新令牌为空, 幂等跳过: account_type=%s", account_type.value)
            return

        try:
            payload = self.jwt_service.verify_refresh(refresh_token)
        except BusinessException as exc:
            if exc.api_code == AuthApiCode.INVALID_TOKEN:
                logger.debug(
                    "刷新令牌无效, 幂等跳过: account_type=%s", account_type.value
                )
                return
            raise

        if payload.account_type != account_type:
            logger.warning(
                "刷新令牌账号类型不匹配, 拒绝登出: expected=%s, actual=%s, account_id=%s",
                account_type.value,
                payload.account_type.value,
                payload.account_id,
            )
            return

        async with self.session.begin():
            auth_session = await self.auth_session_repository.get_by_id_for_update(
                payload.sid
            )
            if (
                auth_session is None
                or auth_session.account_id != payload.account_id
                or auth_session.revoked_at is not None
            ):
                logger.warning(
                    "认证会话无效或已过期, 幂等跳过: sid=%s, account_id=%s",
                    payload.sid,
                    payload.account_id,
                )
                return

            now = utc_now()
            await self.auth_session_repository.revoke(auth_session, now=now)

        logger.info(
            "会话登出成功: sid=%s, account_id=%s", payload.sid, payload.account_id
        )

    async def _rotate_session(
        self, *, payload: RefreshTokenPayload, account_type: AccountType
    ) -> IssuedTokens | None:
        """轮换刷新令牌"""

        # 查询认证会话并加锁
        auth_session = await self.auth_session_repository.get_by_id_for_update(
            payload.sid
        )
        now = utc_now()

        # 会话有效性检查
        if (
            auth_session is None
            or auth_session.account_id != payload.account_id
            or auth_session.revoked_at is not None
            or auth_session.expires_at <= now
        ):
            logger.warning(
                "认证会话无效或已过期: sid=%s, account_id=%s",
                payload.sid,
                payload.account_id,
            )
            return None

        # 重放检查
        if auth_session.refresh_jti != payload.jti:
            logger.warning(
                "检测到旧刷新令牌重用, 撤销会话: sid=%s, account_id=%s",
                auth_session.id,
                auth_session.account_id,
            )
            await self.auth_session_repository.revoke(auth_session, now=now)
            return None

        # 账号状态复查
        authenticated_account = await self.account_authenticator.get_active_account(
            payload.account_id
        )
        if (
            authenticated_account is None
            or authenticated_account.account_type != account_type
        ):
            logger.warning(
                "账号已禁用或类型变更, 撤销会话: sid=%s, account_id=%s",
                auth_session.id,
                auth_session.account_id,
            )
            await self.auth_session_repository.revoke(auth_session, now=now)
            return None

        # 轮换并签发
        new_jti = str(uuid4())
        await self.auth_session_repository.rotate(
            auth_session, refresh_jti=new_jti, now=now
        )
        tokens = self.jwt_service.issue_tokens(
            authenticated_account,
            sid=auth_session.id,
            refresh_jti=new_jti,
            now=now,
            refresh_expires_at=auth_session.expires_at,
        )
        logger.info(
            "刷新会话成功: sid=%s, account_id=%s",
            auth_session.id,
            auth_session.account_id,
        )
        return tokens
