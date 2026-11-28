import math
from contextlib import AbstractAsyncContextManager

from aiobotocore.client import AioBaseClient
from aiobotocore.session import AioSession, get_session
from botocore.config import Config
from pydantic import SecretStr

DEFAULT_S3_CONNECT_TIMEOUT = 2.0
DEFAULT_S3_READ_TIMEOUT = 5.0
DEFAULT_S3_MAX_POOL_CONNECTIONS = 20
DEFAULT_S3_RETRY_MAX_ATTEMPTS = 3


def _unwrap_secret(value: SecretStr | str, *, field_name: str) -> str:
    raw = value.get_secret_value() if isinstance(value, SecretStr) else value
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{field_name} 不能为空")
    return raw


def create_s3_client(
    *,
    endpoint_url: str,
    region_name: str,
    access_key: SecretStr | str,
    secret_key: SecretStr | str,
    read_timeout: float = DEFAULT_S3_READ_TIMEOUT,
    max_pool_connections: int = DEFAULT_S3_MAX_POOL_CONNECTIONS,
    session: AioSession | None = None,
) -> AbstractAsyncContextManager[AioBaseClient]:
    """创建 aiobotocore S3 异步客户端上下文管理器。"""
    if not isinstance(endpoint_url, str) or not endpoint_url.strip():
        raise ValueError("endpoint_url 不能为空")
    if not isinstance(region_name, str) or not region_name.strip():
        raise ValueError("region_name 不能为空")
    if (
        isinstance(read_timeout, bool)
        or not isinstance(read_timeout, (int, float))
        or not math.isfinite(read_timeout)
        or read_timeout <= 0
    ):
        raise ValueError("read_timeout 必须是大于 0 的有限数值")
    if (
        isinstance(max_pool_connections, bool)
        or not isinstance(max_pool_connections, int)
        or max_pool_connections <= 0
    ):
        raise ValueError("max_pool_connections 必须是正整数")

    aws_access_key_id = _unwrap_secret(access_key, field_name="access_key")
    aws_secret_access_key = _unwrap_secret(secret_key, field_name="secret_key")

    config = Config(
        signature_version="s3v4",
        s3={"addressing_style": "path"},
        connect_timeout=DEFAULT_S3_CONNECT_TIMEOUT,
        read_timeout=float(read_timeout),
        max_pool_connections=max_pool_connections,
        retries={
            "mode": "standard",
            "total_max_attempts": DEFAULT_S3_RETRY_MAX_ATTEMPTS,
        },
        request_checksum_calculation="when_required",
        response_checksum_validation="when_required",
    )
    client_session = session if session is not None else get_session()
    return client_session.create_client(
        "s3",
        endpoint_url=endpoint_url,
        region_name=region_name,
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        config=config,
    )
