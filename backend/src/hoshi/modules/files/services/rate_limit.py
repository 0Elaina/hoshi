import logging

from redis import RedisError
from redis.asyncio import Redis

from hoshi.modules.files.constants import (
    FileApiCode,
    FileRedisKey,
    FileUploadConfig,
)
from hoshi.shared.http.api_code import CommonApiCode
from hoshi.shared.http.exception import BusinessException

logger = logging.getLogger(__name__)


class UploadRateLimiter:
    """按账号与来源 IP 对直传授权发放进行固定窗口限流"""

    def __init__(
        self,
        redis: Redis,
        *,
        window_seconds: int = FileUploadConfig.RATE_LIMIT_WINDOW_SECONDS,
        account_limit: int = FileUploadConfig.RATE_LIMIT_ACCOUNT_MAX,
        ip_limit: int = FileUploadConfig.RATE_LIMIT_IP_MAX,
    ) -> None:
        self._redis = redis
        self._window_seconds = window_seconds
        self._account_limit = account_limit
        self._ip_limit = ip_limit

    async def check_upload(self, *, owner_account_id: int, client_ip: str) -> None:
        account_key = f"{FileRedisKey.UPLOAD_RATE_LIMIT_ACCOUNT}{owner_account_id}"
        ip_key = f"{FileRedisKey.UPLOAD_RATE_LIMIT_IP}{client_ip}"

        # 通过单个事务管道原子递增两个计数键并补齐过期时间
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.incr(account_key)
                pipe.expire(account_key, self._window_seconds, nx=True)
                pipe.ttl(account_key)
                pipe.incr(ip_key)
                pipe.expire(ip_key, self._window_seconds, nx=True)
                pipe.ttl(ip_key)
                results = await pipe.execute()
        except (RedisError, TimeoutError, OSError):
            logger.warning(
                "文件上传限流执行失败: owner_account_id=%s client_ip=%s",
                owner_account_id,
                client_ip,
                exc_info=True,
            )
            raise BusinessException(CommonApiCode.SERVICE_UNAVAILABLE) from None

        if len(results) != 6:
            logger.warning(
                "文件上传限流返回异常长度: owner_account_id=%s client_ip=%s len=%s",
                owner_account_id,
                client_ip,
                len(results),
            )
            raise BusinessException(CommonApiCode.SERVICE_UNAVAILABLE)

        account_count, _, account_ttl, ip_count, _, ip_ttl = results

        # 仅收集超额维度的剩余 TTL，并保证 Retry-After 至少为 1 秒
        exceeded_ttls: list[int] = []
        if int(account_count) > self._account_limit:
            exceeded_ttls.append(max(int(account_ttl), 1))
        if int(ip_count) > self._ip_limit:
            exceeded_ttls.append(max(int(ip_ttl), 1))

        if exceeded_ttls:
            retry_after = max(exceeded_ttls)
            logger.warning(
                "文件上传触发限流: owner_account_id=%s client_ip=%s retry_after=%ss",
                owner_account_id,
                client_ip,
                retry_after,
            )
            raise BusinessException(
                FileApiCode.FILE_UPLOAD_RATE_LIMITED,
                headers={"Retry-After": str(retry_after)},
            )
