from pydantic import BaseModel, ConfigDict

from hoshi.modules.auth.enums import AccountRole, AccountType


class AuthenticatedAccount(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: int
    account_type: AccountType
    role: AccountRole


class LoginOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    access_token: str
    expires_in: int


class IssuedTokens(BaseModel):
    model_config = ConfigDict(frozen=True)

    access_token: str
    refresh_token: str
    expires_in: int
