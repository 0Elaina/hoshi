import logging

from redis import RedisError
from redis.asyncio import Redis

from hoshi.modules.auth.constants import REDIS_AUTH_PREFIX, AuthApiCode
from hoshi.modules.auth.enums import AccountType
from hoshi.shared.http.exception import BusinessException

logger = logging.getLogger(__name__)

LOGIN_WINDOW_SECONDS = 300
LOGIN_IP_LIMIT = 60
LOGIN_USERNAME_LIMIT = 10


_RATE_LIMIT_LUA = """
local window = tonumber(ARGV[3])

-- 校验 IP
local ip_count = redis.call('INCR', KEYS[1])
if ip_count == 1 then
    redis.call('EXPIRE', KEYS[1], window)
end

if ip_count > tonumber(ARGV[1]) then
    local ttl = redis.call('TTL', KEYS[1])
    if ttl <= 0 then
        redis.call('EXPIRE', KEYS[1], window)
        ttl = window
    end
    return ttl
end

-- 校验用户名
local user_count = redis.call('INCR', KEYS[2])
if user_count == 1 then
    redis.call('EXPIRE', KEYS[2], window)
end

if user_count > tonumber(ARGV[2]) then
    local ttl = redis.call('TTL', KEYS[2])
    if ttl <= 0 then
        redis.call('EXPIRE', KEYS[2], window)
        ttl = window
    end
    return ttl
end

return 0
"""


class LoginRateLimiter:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._script = redis.register_script(_RATE_LIMIT_LUA)

    async def check_login(
        self, *, account_type: AccountType, client_ip: str, username: str
    ) -> None:
        """检测用户登录"""
        ip_key = f"{REDIS_AUTH_PREFIX}{account_type.value}:login:ip:{client_ip}"
        username_key = (
            f"{REDIS_AUTH_PREFIX}{account_type.value}:login:username:{username}"
        )

        try:
            raw_result = await self._script(
                keys=[ip_key, username_key],
                args=[LOGIN_IP_LIMIT, LOGIN_USERNAME_LIMIT, LOGIN_WINDOW_SECONDS],
            )
        except (RedisError, TimeoutError):
            logger.warning(
                "登录限流执行失败: %s (%s)", username, client_ip, exc_info=True
            )
            raise BusinessException(AuthApiCode.AUTH_TEMPORARILY_UNAVAILABLE) from None

        if raw_result is None:
            logger.warning("登录限流返回为空: %s (%s)", username, client_ip)
            raise BusinessException(AuthApiCode.AUTH_TEMPORARILY_UNAVAILABLE)

        retry_after = int(raw_result)
        if retry_after > 0:
            retry_after = max(retry_after, 1)
            logger.warning(
                "登录触发限流: %s (%s), %ss 后重试", username, client_ip, retry_after
            )
            raise BusinessException(
                AuthApiCode.LOGIN_RATE_LIMITED,
                f"登录尝试过于频繁, 请 {retry_after} 秒后重试",
            )
