from pydantic import BaseModel, ConfigDict

from hoshi.modules.auth.enums import AccountRole, AccountType


class AuthenticatedAccount(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: int
    account_type: AccountType
    role: AccountRole
