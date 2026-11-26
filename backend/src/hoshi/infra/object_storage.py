import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import NoReturn

from aiobotocore.client import AioBaseClient
from aiobotocore.config import AioConfig
from aiobotocore.session import get_session
from botocore.exceptions import BotoCoreError, ClientError

from hoshi.core.config import Settings

logger = logging.getLogger(__name__)

_NOT_FOUND_ERROR_CODES = frozenset({"404", "NoSuchKey", "NotFound"})


@dataclass(frozen=True, slots=True)
class PresignedPut:
    """预签名上传请求信息"""

    url: str
    headers: dict[str, str]


@dataclass(frozen=True, slots=True)
class ObjectMetadata:
    """对象元数据信息"""

    size_bytes: int
    content_type: str | None


class ObjectStorageError(Exception):
    """对象存储操作异常"""

    def __init__(
        self, message: str, *, operation: str, error_code: str | None = None
    ) -> None:
        self.operation = operation
        self.error_code = error_code
        super().__init__(message)


def _validate_object_key(key: str) -> str:
    """校验对象键格式"""
    if not key or key.startswith("/") or any(ch.isspace() for ch in key):
        raise ValueError("对象键不能为空、以 / 开头或包含空白字符")
    return key


def _extract_client_error_code(exc: ClientError) -> str | None:
    """从 Boto3 ClientError 响应中提取错误码"""
    code = exc.response.get("Error", {}).get("Code")
    if isinstance(code, str) and code:
        return code
    return None


def _raise_storage_error(operation: str, exc: ClientError | BotoCoreError) -> NoReturn:
    """记录底层存储异常并统一转换为 ObjectStorageError 抛出"""
    if isinstance(exc, ClientError):
        error_code = _extract_client_error_code(exc)
    else:
        error_code = None
    logger.error(
        "对象存储操作失败, operation=%s, error_code=%s",
        operation,
        error_code,
    )
    raise ObjectStorageError(
        f"对象存储操作 {operation} 失败", operation=operation, error_code=error_code
    ) from exc


@asynccontextmanager
async def open_s3_client(settings: Settings) -> AsyncIterator[AioBaseClient]:
    """创建并管理异步 S3 客户端的生命周期上下文管理器"""

    # 提取认证信息并格式化连接参数
    access_key, secret_key = settings.s3_credentials()
    endpoint_url = str(settings.s3_endpoint_url).rstrip("/")
    region_name = settings.s3_region.strip()
    bucket = settings.s3_bucket.strip()

    # 配置 S3v4 签名与路径风格寻址
    client_config = AioConfig(signature_version="s3v4", s3={"addressing_style": "path"})

    # 初始化异步会话并创建客户端上下文
    session = get_session()
    async with session.create_client(
        "s3",
        endpoint_url=endpoint_url,
        region_name=region_name,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=client_config,
    ) as client:
        try:
            logger.info(
                "S3 客户端已装配, endpoint=%s, region_name=%s, bucket=%s, addressing_style=path",
                endpoint_url,
                region_name,
                bucket,
            )
            yield client
        finally:
            # 确保退出上下文时记录连接关闭日志
            logger.info("S3 客户端已关闭, endpoint=%s, bucket=%s", endpoint_url, bucket)


class S3ObjectStorage:
    """S3 兼容对象存储操作封装"""

    def __init__(self, client: AioBaseClient, bucket: str) -> None:
        """初始化存储客户端并校验存储桶名称"""
        normalized_bucket = bucket.strip()
        if not normalized_bucket:
            raise ValueError("S3 存储桶名称不能为空")
        self._client = client
        self._bucket = normalized_bucket

    async def presign_put(
        self, key: str, *, content_type: str, size_bytes: int, expires_in: int = 300
    ) -> PresignedPut:
        """生成对象上传预签名 URL 及必传请求头"""
        # 前置校验入参，拦截无效的本地签名计算
        _validate_object_key(key)
        normalized_content_type = content_type.strip()
        if not normalized_content_type:
            raise ValueError("Content-Type 不能为空")
        if size_bytes < 0:
            raise ValueError("文件大小不能为负数")
        if expires_in <= 0:
            raise ValueError("签名有效期必须大于 0")

        # 生成 PUT 预签名链接（将类型、大小与防覆盖条件绑定至签名）
        try:
            url = await self._client.generate_presigned_url(
                ClientMethod="put_object",
                Params={
                    "Bucket": self._bucket,
                    "Key": key,
                    "ContentType": normalized_content_type,
                    "ContentLength": size_bytes,
                    "IfNoneMatch": "*",  # 仅允许新建对象，防止覆盖已有文件
                },
                ExpiresIn=expires_in,
                HttpMethod="PUT",
            )  # pyright: ignore
        except (ClientError, BotoCoreError) as exc:
            _raise_storage_error("put_object", exc)

        # 返回签名 URL 及客户端上传时必须原样携带的请求头
        return PresignedPut(
            url=url,
            headers={"Content-Type": normalized_content_type, "If-None-Match": "*"},
        )

    async def presign_get(self, key: str, *, expires_in: int = 300) -> str:
        """生成对象下载预签名 URL"""
        # 校验对象键与有效期
        _validate_object_key(key)
        if expires_in <= 0:
            raise ValueError("签名有效期必须大于 0")

        # 生成 GET 预签名链接并统一转换底层异常
        try:
            url = await self._client.generate_presigned_url(
                ClientMethod="get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expires_in,
                HttpMethod="GET",
            )  # pyright: ignore
        except (ClientError, BotoCoreError) as exc:
            _raise_storage_error("get_object", exc)
        return url

    async def head(self, key: str) -> ObjectMetadata | None:
        """获取对象元数据，若对象不存在则返回 None"""
        # 校验对象键格式
        _validate_object_key(key)

        # 查询对象元信息，将不存在错误码收敛为 None，其余异常统一包装抛出
        try:
            response = await self._client.head_object(Bucket=self._bucket, Key=key)  # pyright: ignore
        except ClientError as exc:
            error_code = _extract_client_error_code(exc)
            if error_code in _NOT_FOUND_ERROR_CODES:
                return None
            _raise_storage_error("head_object", exc)
        except BotoCoreError as exc:
            _raise_storage_error("head_object", exc)

        # 校验响应中的必需字段（ContentLength）并组装元数据模型
        content_length = response.get("ContentLength")
        if content_length is None:
            logger.error("对象存储响应缺少 ContentLength, operation=head_object")
            raise ObjectStorageError(
                "head_object 响应缺少 ContentLength", operation="head_object"
            )
        raw_content_type = response.get("ContentType")
        content_type = str(raw_content_type) if raw_content_type is not None else None
        return ObjectMetadata(
            size_bytes=int(content_length),
            content_type=content_type,
        )

    async def delete(self, key: str) -> None:
        """删除指定对象"""
        # 校验对象键格式
        _validate_object_key(key)

        # 执行删除请求并统一转换底层异常
        try:
            await self._client.delete_object(Bucket=self._bucket, Key=key)  # pyright: ignore
        except (ClientError, BotoCoreError) as exc:
            _raise_storage_error("delete_object", exc)
