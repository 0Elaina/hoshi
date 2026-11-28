from dataclasses import dataclass
from typing import Any

from aiobotocore.client import AioBaseClient
from botocore.exceptions import ClientError

from hoshi.modules.files.object_keys import (
    ASSET_KEY_PREFIX,
    ORIGINAL_ASSET_SEGMENT,
    UPLOAD_KEY_PREFIX,
)

# 预签名有效期与私有读取缓存均固定为 300 秒
PRESIGN_EXPIRES_SECONDS = 300
PRIVATE_ASSET_CACHE_CONTROL = "private, max-age=300"
ORIGINAL_CONTENT_DISPOSITION = "attachment"
IF_NONE_MATCH_ANY = "*"

_OBJECT_NOT_FOUND_CODES = frozenset({"NoSuchKey", "NotFound", "404"})


@dataclass(frozen=True, slots=True)
class PresignedPut:
    url: str
    headers: dict[str, str]


@dataclass(frozen=True, slots=True)
class ObjectMetadata:
    size_bytes: int
    content_type: str | None
    etag: str | None


def _validate_object_key(key: str, *, allowed_prefixes: tuple[str, ...]) -> list[str]:
    """校验对象键前缀、后缀与非法路径段"""
    if not isinstance(key, str) or not key:
        raise ValueError("对象键不能为空")

    matched_prefix = next(
        (prefix for prefix in allowed_prefixes if key.startswith(prefix)), None
    )
    if matched_prefix is None:
        prefixes_text = "、".join(allowed_prefixes)
        raise ValueError(f"对象键必须以 {prefixes_text} 开头")

    object_path = key[len(matched_prefix) :]
    if not object_path or not object_path.strip():
        raise ValueError("对象键前缀后必须包含有效对象路径")

    # 拒绝空段、当前目录与上级目录路径段
    segments = key.split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        raise ValueError("对象键包含非法路径段")

    return segments


def _is_object_not_found(exc: ClientError, *, allow_generic_404: bool) -> bool:
    """判断 ClientError 是否明确表示对象缺失"""
    response = exc.response
    error = response.get("Error") or {}
    code = str(error.get("Code") or "")
    status_code = (response.get("ResponseMetadata") or {}).get("HTTPStatusCode")

    # 桶缺失与权限拒绝须继续抛出，不能伪装成对象不存在
    if code == "NoSuchBucket" or status_code == 403 or code in {"AccessDenied", "403"}:
        return False

    if code in _OBJECT_NOT_FOUND_CODES:
        return True

    # HEAD 在已建桶上可能仅返回通用 404
    return allow_generic_404 and status_code == 404 and not code


class FileObjectStorage:
    """私有桶对象存储适配器"""

    def __init__(
        self,
        client: AioBaseClient,
        signing_client: AioBaseClient,
        bucket_name: str,
    ) -> None:
        if client is None:
            raise ValueError("client 不能为空")
        if signing_client is None:
            raise ValueError("signing_client 不能为空")
        if not isinstance(bucket_name, str) or not bucket_name.strip():
            raise ValueError("bucket_name 不能为空")

        # 内部 I/O 与浏览器预签名分别持有对应客户端实例
        self._client: Any = client
        self._signing_client: Any = signing_client
        self._bucket_name = bucket_name

    async def presign_put(
        self, key: str, content_type: str, size_bytes: int
    ) -> PresignedPut:
        """为 uploads/ 临时上传键签发带长度和条件写入约束的 PUT 预签名"""
        _validate_object_key(key, allowed_prefixes=(UPLOAD_KEY_PREFIX,))

        if (
            not isinstance(content_type, str)
            or not (normalized_content_type := content_type.strip())
            or "\r" in normalized_content_type
            or "\n" in normalized_content_type
        ):
            raise ValueError("content_type 必须是非空单行 MIME 类型")

        if (
            isinstance(size_bytes, bool)
            or not isinstance(size_bytes, int)
            or size_bytes <= 0
        ):
            raise ValueError("size_bytes 必须是正整数")

        # Content-Length 由浏览器上传 File 时自动生成，headers 仅返回额外需显式携带的请求头
        url: str = await self._signing_client.generate_presigned_url(
            ClientMethod="put_object",
            Params={
                "Bucket": self._bucket_name,
                "Key": key,
                "ContentType": normalized_content_type,
                "ContentLength": size_bytes,
                "IfNoneMatch": IF_NONE_MATCH_ANY,
            },
            ExpiresIn=PRESIGN_EXPIRES_SECONDS,
            HttpMethod="PUT",
        )
        return PresignedPut(
            url=url,
            headers={
                "Content-Type": normalized_content_type,
                "If-None-Match": IF_NONE_MATCH_ANY,
            },
        )

    async def presign_get(self, key: str) -> str:
        """为业务已授权的 assets/ 键签发私有 GET 预签名 URL"""
        segments = _validate_object_key(key, allowed_prefixes=(ASSET_KEY_PREFIX,))

        params: dict[str, Any] = {
            "Bucket": self._bucket_name,
            "Key": key,
            "ResponseCacheControl": PRIVATE_ASSET_CACHE_CONTROL,
        }
        # 原文件读取强制以附件形式下载，防止浏览器内联执行不可信内容
        if len(segments) >= 4 and segments[3] == ORIGINAL_ASSET_SEGMENT:
            params["ResponseContentDisposition"] = ORIGINAL_CONTENT_DISPOSITION

        url: str = await self._signing_client.generate_presigned_url(
            ClientMethod="get_object",
            Params=params,
            ExpiresIn=PRESIGN_EXPIRES_SECONDS,
            HttpMethod="GET",
        )
        return url

    async def head(self, key: str) -> ObjectMetadata | None:
        """查询 uploads/ 或 assets/ 对象的元信息，对象缺失返回 None"""
        _validate_object_key(
            key, allowed_prefixes=(UPLOAD_KEY_PREFIX, ASSET_KEY_PREFIX)
        )

        try:
            response: dict[str, Any] = await self._client.head_object(
                Bucket=self._bucket_name,
                Key=key,
            )
        except ClientError as exc:
            if _is_object_not_found(exc, allow_generic_404=True):
                return None
            raise

        # ETag 原样保留，不做引号剥离
        return ObjectMetadata(
            size_bytes=int(response["ContentLength"]),
            content_type=response.get("ContentType"),
            etag=response.get("ETag"),
        )

    async def delete_upload(self, key: str) -> None:
        """删除 uploads/ 暂存对象，成功或对象已缺失均返回 None"""
        _validate_object_key(key, allowed_prefixes=(UPLOAD_KEY_PREFIX,))

        try:
            await self._client.delete_object(
                Bucket=self._bucket_name,
                Key=key,
            )
        except ClientError as exc:
            if _is_object_not_found(exc, allow_generic_404=False):
                return
            raise
