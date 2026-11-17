from enum import StrEnum


class AccountType(StrEnum):
    ADMIN = "admin"
    USER = "user"


class AccountRole(StrEnum):
    ADMIN = "admin"
    USER = "user"


class AccountStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


ROLES_BY_ACCOUNT_TYPE: dict[AccountType, frozenset[AccountRole]] = {
    AccountType.ADMIN: frozenset({AccountRole.ADMIN}),
    AccountType.USER: frozenset({AccountRole.USER}),
}
