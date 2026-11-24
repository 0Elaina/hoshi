from typing import Self

from pydantic import BaseModel, ConfigDict, Field

from hoshi.modules.auth.enums import AccountRole, AccountType
from hoshi.modules.user.models import UserAccount


class CurrentAccountOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    username: str
    nickname: str
    account_type: AccountType = Field(serialization_alias="accountType")
    role: AccountRole

    @classmethod
    def of(cls, account: UserAccount) -> Self:
        return cls(
            id=str(account.id),
            username=account.username,
            nickname=account.nickname,
            account_type=AccountType(account.account_type),
            role=AccountRole(account.role),
        )
