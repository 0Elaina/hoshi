from fastapi import status

from hoshi.shared.http.api_code import ApiCode

REDIS_AUTH_PREFIX = "hoshi:auth:"


class AuthApiCode:
    INVALID_CREDENTIALS = ApiCode(
        status.HTTP_401_UNAUTHORIZED, "INVALID_CREDENTIALS", "用户名或密码错误"
    )
    INVALID_TOKEN = ApiCode(
        status.HTTP_401_UNAUTHORIZED, "INVALID_TOKEN", "认证令牌无效或已过期"
    )

    INVALID_AUTH_ORIGIN = ApiCode(
        status.HTTP_403_FORBIDDEN, "INVALID_AUTH_ORIGIN", "请求来源不受信任"
    )
    ACCESS_DENIED = ApiCode(
        status.HTTP_403_FORBIDDEN, "ACCESS_DENIED", "无权访问当前入口"
    )

    LOGIN_RATE_LIMITED = ApiCode(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "LOGIN_RATE_LIMITED",
        "登录尝试过于频繁，请稍后重试",
    )

    AUTH_TEMPORARILY_UNAVAILABLE = ApiCode(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "AUTH_TEMPORARILY_UNAVAILABLE",
        "登录服务暂不可用，请稍后重试",
    )
