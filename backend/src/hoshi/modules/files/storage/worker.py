from dataclasses import dataclass
from typing import Any

from aiobotocore.client import AioBaseClient
from botocore.exceptions import (
    ClientError,
    ConnectionClosedError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ProxyConnectionError,
    ReadTimeoutError,
)

# Worker 侧流式读取块大小与可重试上游错误分类
_READ_CHUNK_BYTES = 64 * 1024
_RETRYABLE_BOTOCORE_EXCEPTIONS = (
    EndpointConnectionError,
    ProxyConnectionError,
    ConnectionClosedError,
    ConnectTimeoutError,
    ReadTimeoutError,
)
_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
_RETRYABLE_ERROR_CODES = frozenset({"SlowDown", "RequestTimeout", "ServiceUnavailable"})


@dataclass(frozen=True, slots=True)
class ObjectReadTooLarge:
    """流式读取对象超出最大字节数时的结构化结果（避免用自定义异常表达可预期拒绝）"""

    max_bytes: int
    read_bytes: int


def is_precondition_failed(exc: ClientError) -> bool:
    """判断 S3 条件请求（如 If-Match）是否返回 412"""
    response = exc.response
    code = str((response.get("Error") or {}).get("Code") or "")
    status_code = (response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
    return status_code == 412 or code == "PreconditionFailed"


def is_object_missing_error(exc: ClientError) -> bool:
    """判断对象读取或删除是否返回明确的 NoSuchKey"""
    response = exc.response
    code = str((response.get("Error") or {}).get("Code") or "")
    status_code = (response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
    if code == "NoSuchBucket" or status_code == 403 or code in {"AccessDenied", "403"}:
        return False
    return code == "NoSuchKey"


def is_retryable_storage_error(exc: Exception) -> bool:
    """判断 S3 SDK 异常是否属于连接、超时或上游限流/服务端暂态故障"""
    if isinstance(exc, _RETRYABLE_BOTOCORE_EXCEPTIONS):
        return True
    if isinstance(exc, ClientError):
        response = exc.response
        code = str((response.get("Error") or {}).get("Code") or "")
        status_code = (response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
        return status_code in _RETRYABLE_STATUS_CODES or code in _RETRYABLE_ERROR_CODES
    return False


class WorkerObjectStorage:
    """Worker 专用的双桶对象读写与删除适配器，保留原始 SDK 异常供任务状态机判断"""

    def __init__(
        self,
        client: AioBaseClient,
        *,
        private_bucket: str,
        public_bucket: str,
    ) -> None:
        if not private_bucket or not public_bucket:
            raise ValueError("private_bucket 与 public_bucket 不能为空")
        self._client: Any = client
        self.private_bucket = private_bucket
        self.public_bucket = public_bucket

    async def get_object_bytes(
        self,
        *,
        bucket: str,
        key: str,
        if_match: str | None = None,
        max_bytes: int | None = None,
    ) -> bytes | ObjectReadTooLarge:
        """按分块读取对象字节，超限时返回结构化 ObjectReadTooLarge 而不抛自定义异常"""
        params: dict[str, Any] = {"Bucket": bucket, "Key": key}
        if if_match is not None:
            params["IfMatch"] = if_match

        response: dict[str, Any] = await self._client.get_object(**params)
        body = response["Body"]
        chunks: list[bytes] = []
        total_read = 0
        try:
            while True:
                chunk: bytes = await body.read(_READ_CHUNK_BYTES)
                if not chunk:
                    break
                total_read += len(chunk)
                # 流式读取阶段即截断超限载荷并返回结构化结果，防止大对象撑爆 Worker 内存
                if max_bytes is not None and total_read > max_bytes:
                    return ObjectReadTooLarge(
                        max_bytes=max_bytes,
                        read_bytes=total_read,
                    )
                chunks.append(chunk)
        finally:
            body.close()

        return b"".join(chunks)

    async def put_object_bytes(
        self,
        *,
        bucket: str,
        key: str,
        data: bytes,
        content_type: str,
        cache_control: str | None = None,
    ) -> None:
        """将校验后的原件或生成衍生物写入目标桶"""
        params: dict[str, Any] = {
            "Bucket": bucket,
            "Key": key,
            "Body": data,
            "ContentType": content_type,
            "ContentLength": len(data),
        }
        if cache_control is not None:
            params["CacheControl"] = cache_control
        await self._client.put_object(**params)

    async def delete_object_if_exists(self, *, bucket: str, key: str) -> None:
        """删除单个对象；仅吞明确的 NoSuchKey，桶缺失/403/通用 404 均保留抛出"""
        try:
            await self._client.delete_object(Bucket=bucket, Key=key)
        except ClientError as exc:
            if is_object_missing_error(exc):
                return
            raise
