from collections.abc import Mapping
from enum import Enum, StrEnum
from types import MappingProxyType
from typing import Protocol, Self, runtime_checkable


class MediaKind(StrEnum):
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"


class FileAssetStatus(StrEnum):
    PENDING_UPLOAD = "pending_upload"
    UPLOAD_REJECTED = "upload_rejected"
    PENDING_VALIDATION = "pending_validation"
    READY = "ready"
    VALIDATION_REJECTED = "validation_rejected"
    VALIDATION_FAILED = "validation_failed"


class FileJobType(StrEnum):
    VALIDATE_UPLOAD = "validate_upload"
    GENERATE_VARIANT = "generate_variant"
    CLEANUP_VARIANT = "cleanup_variant"
    PURGE_VARIANT_CACHE = "purge_variant_cache"


class FileJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class FileVariantVisibility(StrEnum):
    PRIVATE = "private"
    PUBLIC = "public"


class FileVariantStatus(StrEnum):
    UNAVAILABLE = "unavailable"
    READY = "ready"
    WITHDRAWN = "withdrawn"


class MediaFormat(Enum):
    """受支持媒体格式的单一事实源，统一维护 MIME、解码格式名与扩展名"""

    JPEG = (MediaKind.IMAGE, "image/jpeg", "JPEG", "jpg")
    PNG = (MediaKind.IMAGE, "image/png", "PNG", "png")
    WEBP = (MediaKind.IMAGE, "image/webp", "WEBP", "webp")

    media_kind: MediaKind
    mime_type: str
    format_name: str
    extension: str

    def __new__(
        cls,
        media_kind: MediaKind,
        mime_type: str,
        format_name: str,
        extension: str,
    ) -> Self:
        obj = object.__new__(cls)
        obj._value_ = mime_type
        obj.media_kind = media_kind
        obj.mime_type = mime_type
        obj.format_name = format_name
        obj.extension = extension
        return obj

    @classmethod
    def from_mime_type(cls, mime_type: str) -> "MediaFormat | None":
        """按规范化后的小写 MIME 反查媒体格式"""
        return _MEDIA_FORMAT_BY_MIME.get(mime_type)

    @classmethod
    def from_format_name(cls, format_name: str) -> "MediaFormat | None":
        """按解码器格式名反查媒体格式"""
        return _MEDIA_FORMAT_BY_NAME.get(format_name.upper())


@runtime_checkable
class VariantPreset(Protocol):
    """各媒体大类衍生规格枚举共享的最小契约"""

    @property
    def media_kind(self) -> MediaKind: ...

    @property
    def preset_name(self) -> str: ...

    @property
    def revision(self) -> int: ...

    @property
    def output_format(self) -> MediaFormat: ...


class ImagePreset(Enum):
    """图片衍生规格预设（其他媒体大类后续按各自转码参数独立建枚举）"""

    # 原图级展示规格：保持原尺寸，仅做 EXIF 方向纠正、去元数据并转为 WebP
    FULL_V1 = ("full", 1, MediaFormat.WEBP, 85)

    media_kind: MediaKind
    preset_name: str
    revision: int
    output_format: MediaFormat
    quality: int

    def __new__(
        cls,
        preset_name: str,
        revision: int,
        output_format: MediaFormat,
        quality: int,
    ) -> Self:
        obj = object.__new__(cls)
        obj._value_ = f"{preset_name}:v{revision}"
        obj.media_kind = MediaKind.IMAGE
        obj.preset_name = preset_name
        obj.revision = revision
        obj.output_format = output_format
        obj.quality = quality
        return obj

    @classmethod
    def from_name_and_revision(
        cls, preset_name: str, revision: int
    ) -> "ImagePreset | None":
        """按规格名与版本号反查图片规格预设"""
        if isinstance(revision, bool) or not isinstance(revision, int):
            return None
        return _IMAGE_PRESET_BY_KEY.get((preset_name, revision))


_MEDIA_FORMAT_BY_MIME: Mapping[str, MediaFormat] = MappingProxyType(
    {fmt.mime_type: fmt for fmt in MediaFormat}
)
_MEDIA_FORMAT_BY_NAME: Mapping[str, MediaFormat] = MappingProxyType(
    {fmt.format_name.upper(): fmt for fmt in MediaFormat}
)
_IMAGE_PRESET_BY_KEY: Mapping[tuple[str, int], ImagePreset] = MappingProxyType(
    {(preset.preset_name, preset.revision): preset for preset in ImagePreset}
)
_PRESET_REGISTRY_BY_KIND: Mapping[
    MediaKind, Mapping[tuple[str, int], VariantPreset]
] = MappingProxyType(
    {
        MediaKind.IMAGE: _IMAGE_PRESET_BY_KEY,
    }
)


def lookup_variant_preset(
    media_kind: MediaKind, preset_name: str, revision: int
) -> VariantPreset | None:
    """按媒体类型、规格名与版本号反查已登记规格预设"""
    if isinstance(revision, bool) or not isinstance(revision, int):
        return None
    registry = _PRESET_REGISTRY_BY_KIND.get(media_kind)
    if registry is None:
        return None
    return registry.get((preset_name, revision))
