import re
from enum import StrEnum
from uuid import UUID

UPLOAD_KEY_PREFIX = "uploads/"
ASSET_KEY_PREFIX = "assets/"
ORIGINAL_ASSET_SEGMENT = "original"
VARIANTS_ASSET_SEGMENT = "variants"

# 规格名以小写字母开头，扩展名仅限无前导点的小写 ASCII 字母数字
_PRESET_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,63}$", re.ASCII)
_EXTENSION_PATTERN = re.compile(r"^[a-z0-9]{1,16}$", re.ASCII)


class MediaKind(StrEnum):
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"


def _validate_uuid4_hex(value: UUID, *, field_name: str) -> str:
    # 资产 ID 与物理对象 ID 统一使用 UUID v4 小写 hex
    if not isinstance(value, UUID) or value.version != 4:
        raise ValueError(f"{field_name} 必须是 UUID v4")
    return value.hex


def _validate_media_kind(media_kind: MediaKind) -> MediaKind:
    if isinstance(media_kind, MediaKind):
        return media_kind
    raise ValueError("media_kind 必须是有效的 MediaKind 枚举值")


def _validate_preset_name(preset_name: str) -> str:
    if not isinstance(preset_name, str) or not _PRESET_NAME_PATTERN.fullmatch(
        preset_name
    ):
        raise ValueError(
            "preset_name 须以小写字母开头，仅含小写字母、数字和短横线，长度 1 至 64 字符"
        )
    return preset_name


def _validate_preset_revision(preset_revision: int) -> int:
    # 排除 bool（Python 中 bool 是 int 子类）
    if (
        isinstance(preset_revision, bool)
        or not isinstance(preset_revision, int)
        or preset_revision < 1
    ):
        raise ValueError("preset_revision 必须是正整数")
    return preset_revision


def _validate_extension(extension: str) -> str:
    if not isinstance(extension, str) or not _EXTENSION_PATTERN.fullmatch(extension):
        raise ValueError("extension 必须是 1 至 16 位小写 ASCII 字母或数字，不含前导点")
    return extension


def build_upload_key(asset_id: UUID) -> str:
    """构造私有待校验上传对象键"""
    asset_hex = _validate_uuid4_hex(asset_id, field_name="asset_id")
    return f"{UPLOAD_KEY_PREFIX}{asset_hex}/source"


def build_original_key(media_kind: MediaKind, asset_id: UUID, object_id: UUID) -> str:
    """构造私有原文件对象键"""
    kind = _validate_media_kind(media_kind)
    asset_hex = _validate_uuid4_hex(asset_id, field_name="asset_id")
    object_hex = _validate_uuid4_hex(object_id, field_name="object_id")
    return (
        f"{ASSET_KEY_PREFIX}{kind.value}/{asset_hex}/"
        f"{ORIGINAL_ASSET_SEGMENT}/{object_hex}"
    )


def build_variant_key(
    media_kind: MediaKind,
    asset_id: UUID,
    preset_name: str,
    preset_revision: int,
    object_id: UUID,
    extension: str,
) -> str:
    """构造私有或公开衍生物对象键"""
    kind = _validate_media_kind(media_kind)
    asset_hex = _validate_uuid4_hex(asset_id, field_name="asset_id")
    valid_preset_name = _validate_preset_name(preset_name)
    valid_revision = _validate_preset_revision(preset_revision)
    object_hex = _validate_uuid4_hex(object_id, field_name="object_id")
    valid_extension = _validate_extension(extension)
    return (
        f"{ASSET_KEY_PREFIX}{kind.value}/{asset_hex}/{VARIANTS_ASSET_SEGMENT}/"
        f"{valid_preset_name}/v{valid_revision}/{object_hex}.{valid_extension}"
    )
