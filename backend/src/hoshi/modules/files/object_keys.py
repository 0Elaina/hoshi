from uuid import UUID

from hoshi.modules.files.enums import (
    MediaKind,
    VariantPreset,
    lookup_variant_preset,
)


class ObjectKeyLayout:
    """对象键前缀与固定路径段常量"""

    UPLOAD_PREFIX = "uploads/"
    ASSET_PREFIX = "assets/"
    ORIGINAL_SEGMENT = "original"
    VARIANTS_SEGMENT = "variants"


def _validate_uuid4_hex(value: UUID, *, field_name: str) -> str:
    # 资产 ID 与物理对象 ID 统一使用 UUID v4 小写 hex
    if not isinstance(value, UUID) or value.version != 4:
        raise ValueError(f"{field_name} 必须是 UUID v4")
    return value.hex


def _validate_media_kind(media_kind: MediaKind) -> MediaKind:
    if isinstance(media_kind, MediaKind):
        return media_kind
    raise ValueError("media_kind 必须是有效的 MediaKind 枚举值")


def _validate_variant_preset(preset: VariantPreset) -> VariantPreset:
    # 仅允许已登记的规格枚举实例参与键构造
    if isinstance(preset, VariantPreset):
        registered = lookup_variant_preset(
            preset.media_kind, preset.preset_name, preset.revision
        )
        if registered is preset:
            return preset
    raise ValueError("preset 必须是已登记的衍生规格枚举值")


def build_upload_key(asset_id: UUID) -> str:
    """构造私有待校验上传对象键"""
    asset_hex = _validate_uuid4_hex(asset_id, field_name="asset_id")
    return f"{ObjectKeyLayout.UPLOAD_PREFIX}{asset_hex}/source"


def build_original_key(media_kind: MediaKind, asset_id: UUID, object_id: UUID) -> str:
    """构造私有原文件对象键"""
    kind = _validate_media_kind(media_kind)
    asset_hex = _validate_uuid4_hex(asset_id, field_name="asset_id")
    object_hex = _validate_uuid4_hex(object_id, field_name="object_id")
    return (
        f"{ObjectKeyLayout.ASSET_PREFIX}{kind.value}/{asset_hex}/"
        f"{ObjectKeyLayout.ORIGINAL_SEGMENT}/{object_hex}"
    )


def build_variant_key(asset_id: UUID, preset: VariantPreset, object_id: UUID) -> str:
    """按已登记规格预设构造私有或公开衍生物对象键"""
    asset_hex = _validate_uuid4_hex(asset_id, field_name="asset_id")
    valid_preset = _validate_variant_preset(preset)
    object_hex = _validate_uuid4_hex(object_id, field_name="object_id")
    return (
        f"{ObjectKeyLayout.ASSET_PREFIX}{valid_preset.media_kind.value}/{asset_hex}/"
        f"{ObjectKeyLayout.VARIANTS_SEGMENT}/{valid_preset.preset_name}/"
        f"v{valid_preset.revision}/{object_hex}.{valid_preset.output_format.extension}"
    )
