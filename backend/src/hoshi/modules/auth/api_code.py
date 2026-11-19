from fastapi import status

from hoshi.shared.http.api_code import ApiCode


class AuthApiCode:
    INVALID_CREDENTIALS = ApiCode(
        status.HTTP_401_UNAUTHORIZED, "INVALID_CREDENTIALS", "用户名或密码错误"
    )
    INVALID_TOKEN = ApiCode(
        status.HTTP_401_UNAUTHORIZED, "INVALID_TOKEN", "认证令牌无效或已过期"
    )
