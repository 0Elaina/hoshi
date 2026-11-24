from fastapi import status

from hoshi.shared.http.api_code import ApiCode


class UserApiCode:
    ACCOUNT_UNAVAILABLE = ApiCode(
        status.HTTP_403_FORBIDDEN,
        "ACCOUNT_UNAVAILABLE",
        "当前账号不可用",
    )
