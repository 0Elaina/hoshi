from pydantic import BaseModel, ConfigDict, Field

from hoshi.modules.auth.enums import AccountRole, AccountType


class AuthenticatedAccount(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: int
    account_type: AccountType
    role: AccountRole


class LoginOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    access_token: str = Field(serialization_alias="accessToken")
    expires_in: int = Field(serialization_alias="expiresIn")


class IssuedTokens(BaseModel):
    model_config = ConfigDict(frozen=True)

    access_token: str = Field(serialization_alias="accessToken")
    refresh_token: str = Field(serialization_alias="refreshToken")
    expires_in: int = Field(serialization_alias="expiresIn")


class AccessTokenPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    account_id: int
    account_type: AccountType


class RefreshTokenPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    account_id: int
    account_type: AccountType
    sid: str
    jti: str


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=128)
