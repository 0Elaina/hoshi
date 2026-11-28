from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from fastapi import status

from hoshi.modules.files.enums import MediaFormat, MediaKind
from hoshi.shared.http.api_code import ApiCode


@dataclass(frozen=True, slots=True)
class MediaUploadRule:
    allowed_formats: frozenset[MediaFormat]
    max_size_bytes: int


class FileRedisKey:
    """文件模块使用的 Redis 键前缀"""

    PREFIX = "hoshi:files:"
    UPLOAD_RATE_LIMIT_ACCOUNT = f"{PREFIX}upload:ratelimit:account:"
    UPLOAD_RATE_LIMIT_IP = f"{PREFIX}upload:ratelimit:ip:"


class FileUploadConfig:
    """直传窗口、限流阈值与媒体大小上限"""

    CONFIRM_TTL_SECONDS = 15 * 60
    RATE_LIMIT_WINDOW_SECONDS = 60
    RATE_LIMIT_ACCOUNT_MAX = 10
    RATE_LIMIT_IP_MAX = 60
    IMAGE_MAX_SIZE_BYTES = 10 * 1024 * 1024
    MAX_MIME_LENGTH = 127


class FileJobTiming:
    """文件后台任务调度与重试相关时间配置"""

    MQ_INITIAL_WAKEUP_DELAY_SECONDS = 60


MEDIA_UPLOAD_RULES: Mapping[MediaKind, MediaUploadRule] = MappingProxyType(
    {
        MediaKind.IMAGE: MediaUploadRule(
            allowed_formats=frozenset(
                {MediaFormat.JPEG, MediaFormat.PNG, MediaFormat.WEBP}
            ),
            max_size_bytes=FileUploadConfig.IMAGE_MAX_SIZE_BYTES,
        ),
    }
)


class FileApiCode:
    FILE_ASSET_NOT_FOUND = ApiCode(
        status.HTTP_404_NOT_FOUND, "FILE_ASSET_NOT_FOUND", "文件资产不存在"
    )
    FILE_UPLOAD_NOT_RECEIVED = ApiCode(
        status.HTTP_409_CONFLICT, "FILE_UPLOAD_NOT_RECEIVED", "尚未收到上传文件"
    )
    FILE_UPLOAD_METADATA_MISMATCH = ApiCode(
        status.HTTP_409_CONFLICT,
        "FILE_UPLOAD_METADATA_MISMATCH",
        "上传文件元信息与登记不符",
    )
    FILE_ASSET_NOT_READY = ApiCode(
        status.HTTP_409_CONFLICT, "FILE_ASSET_NOT_READY", "文件资产尚未就绪"
    )
    FILE_VARIANT_WITHDRAWN = ApiCode(
        status.HTTP_409_CONFLICT, "FILE_VARIANT_WITHDRAWN", "目标文件规格已撤回"
    )
    FILE_UPLOAD_EXPIRED = ApiCode(
        status.HTTP_410_GONE, "FILE_UPLOAD_EXPIRED", "文件上传确认窗口已过期"
    )
    FILE_UPLOAD_TOO_LARGE = ApiCode(
        status.HTTP_413_CONTENT_TOO_LARGE,
        "FILE_UPLOAD_TOO_LARGE",
        "上传文件大小超出限制",
    )
    FILE_UPLOAD_UNSUPPORTED_MEDIA = ApiCode(
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        "FILE_UPLOAD_UNSUPPORTED_MEDIA",
        "不支持的文件媒体类型",
    )
    FILE_UPLOAD_RATE_LIMITED = ApiCode(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "FILE_UPLOAD_RATE_LIMITED",
        "上传请求过于频繁，请稍后重试",
    )
