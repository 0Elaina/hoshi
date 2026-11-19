from datetime import datetime, timedelta
from typing import Any

import jwt

from hoshi.core.config import Settings
from hoshi.modules.auth.api_code import AuthApiCode
from hoshi.modules.auth.enums import AccountType, TokenType
from hoshi.modules.auth.schemas import (
    AccessTokenPayload,
    AuthenticatedAccount,
    IssuedTokens,
    RefreshTokenPayload,
)
from hoshi.shared.http.exception import BusinessException

JWT_ALGORITHM = "HS256"
ISS = "iss"
SUB = "sub"
IAT = "iat"
EXP = "exp"
ACCOUNT_TYPE = "account_type"
TOKEN_TYPE = "token_type"
SID = "sid"
JTI = "jti"


class JwtService:
    def __init__(self, settings: Settings) -> None:
        self._secret = settings.jwt_secret_bytes()
        self._issuer = settings.jwt_issuer
        self.jwt_access_ttl = timedelta(seconds=settings.jwt_access_ttl)

    def _decode_token(
        self, token: str, *, expected_type: TokenType, required_claims: list[str]
    ) -> dict[str, Any]:
        """解码令牌"""

        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[JWT_ALGORITHM],
                issuer=self._issuer,
                options={"require": required_claims},
            )
        except jwt.PyJWTError:
            raise BusinessException(AuthApiCode.INVALID_TOKEN) from None
        if payload.get(TOKEN_TYPE) != expected_type.value:
            raise BusinessException(AuthApiCode.INVALID_TOKEN)
        return payload

    def _parse_account_sub_and_type(
        self, payload: dict[str, Any]
    ) -> tuple[int, AccountType]:
        """解析令牌中的账户ID和账户类型"""

        raw_sub, raw_account_type = payload[SUB], payload[ACCOUNT_TYPE]
        if (
            not isinstance(raw_sub, str)
            or not raw_sub.isdecimal()
            or not isinstance(raw_account_type, str)
        ):
            raise BusinessException(AuthApiCode.INVALID_TOKEN)

        account_id = int(raw_sub)
        if account_id <= 0:
            raise BusinessException(AuthApiCode.INVALID_TOKEN)

        try:
            account_type = AccountType(payload[ACCOUNT_TYPE])
        except ValueError:
            raise BusinessException(AuthApiCode.INVALID_TOKEN) from None
        return account_id, account_type

    def issue_tokens(
        self,
        authenticated_account: AuthenticatedAccount,
        *,
        sid: str,
        refresh_jti: str,
        now: datetime,
        refresh_expires_at: datetime,
    ) -> IssuedTokens:
        """签发双令牌"""

        access_expires_at = min(now + self.jwt_access_ttl, refresh_expires_at)

        access_payload = {
            ISS: self._issuer,
            SUB: str(authenticated_account.id),
            IAT: now,
            EXP: access_expires_at,
            ACCOUNT_TYPE: authenticated_account.account_type.value,
            TOKEN_TYPE: TokenType.ACCESS.value,
        }

        refresh_payload = {
            ISS: self._issuer,
            SUB: str(authenticated_account.id),
            IAT: now,
            EXP: refresh_expires_at,
            ACCOUNT_TYPE: authenticated_account.account_type.value,
            TOKEN_TYPE: TokenType.REFRESH.value,
            SID: sid,
            JTI: refresh_jti,
        }

        access_token = jwt.encode(access_payload, self._secret, algorithm=JWT_ALGORITHM)
        refresh_token = jwt.encode(
            refresh_payload, self._secret, algorithm=JWT_ALGORITHM
        )
        expires_in = int((access_expires_at - now).total_seconds())

        return IssuedTokens(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
        )

    def verify_access(self, token: str) -> AccessTokenPayload:
        """验证访问令牌"""

        required_claims = [ISS, SUB, IAT, EXP, ACCOUNT_TYPE, TOKEN_TYPE]
        payload = self._decode_token(
            token, expected_type=TokenType.ACCESS, required_claims=required_claims
        )
        account_id, account_type = self._parse_account_sub_and_type(payload)
        return AccessTokenPayload(account_id=account_id, account_type=account_type)

    def verify_refresh(self, token: str) -> RefreshTokenPayload:
        """验证刷新令牌"""

        required_claims = [ISS, SUB, IAT, EXP, ACCOUNT_TYPE, TOKEN_TYPE, SID, JTI]
        payload = self._decode_token(
            token, expected_type=TokenType.REFRESH, required_claims=required_claims
        )
        account_id, account_type = self._parse_account_sub_and_type(payload)
        sid, jti = payload[SID], payload[JTI]
        if not isinstance(sid, str) or not isinstance(jti, str):
            raise BusinessException(AuthApiCode.INVALID_TOKEN)
        if not sid or not jti:
            raise BusinessException(AuthApiCode.INVALID_TOKEN)
        return RefreshTokenPayload(
            account_id=account_id,
            account_type=account_type,
            sid=sid,
            jti=jti,
        )
