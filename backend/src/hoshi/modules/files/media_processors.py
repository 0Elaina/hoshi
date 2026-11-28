from dataclasses import dataclass
from io import BytesIO

from PIL import Image, UnidentifiedImageError

from hoshi.modules.files.constants import FileUploadConfig
from hoshi.modules.files.enums import MediaFormat, MediaKind

# 图片解码安全阈值，防范解压炸弹与异常超高分辨率
MAX_IMAGE_PIXELS = 25_000_000
MAX_IMAGE_DIMENSION = 8192


@dataclass(frozen=True, slots=True)
class ValidatedImageInfo:
    content_type: str
    size_bytes: int
    width: int
    height: int


class ImageValidationError(Exception):
    """图片内容校验拒绝异常，供 Worker 映射为 validation_rejected"""

    def __init__(self, error_code: str, summary: str) -> None:
        self.error_code = error_code
        self.summary = summary
        super().__init__(summary)


def validate_image_bytes(
    data: bytes,
    *,
    declared_content_type: str,
    declared_size_bytes: int,
) -> ValidatedImageInfo:
    """同步校验图片实际体积、分辨率安全边界与 Pillow 完整解码一致性"""
    actual_size = len(data)
    if actual_size <= 0 or actual_size != declared_size_bytes:
        raise ImageValidationError(
            "IMAGE_SIZE_MISMATCH",
            f"实际大小 {actual_size} 与登记大小 {declared_size_bytes} 不符",
        )
    if actual_size > FileUploadConfig.IMAGE_MAX_SIZE_BYTES:
        raise ImageValidationError(
            "IMAGE_TOO_LARGE",
            f"实际大小 {actual_size} 超出上限 {FileUploadConfig.IMAGE_MAX_SIZE_BYTES}",
        )

    # 先基于容器头检查格式与宽高，再执行 verify() 校验结构完整性
    try:
        with Image.open(BytesIO(data)) as probe:
            detected_format_name = (probe.format or "").upper()
            detected_format = MediaFormat.from_format_name(detected_format_name)
            # 校验实际解码格式属于图片且与声明 MIME 严格一致
            if (
                detected_format is None
                or detected_format.media_kind != MediaKind.IMAGE
                or detected_format.mime_type != declared_content_type
            ):
                raise ImageValidationError(
                    "IMAGE_FORMAT_MISMATCH",
                    f"检测到格式 {detected_format_name or 'unknown'} 与声明 {declared_content_type} 不符",
                )

            width, height = probe.size
            if (
                width <= 0
                or height <= 0
                or width > MAX_IMAGE_DIMENSION
                or height > MAX_IMAGE_DIMENSION
                or width * height > MAX_IMAGE_PIXELS
            ):
                raise ImageValidationError(
                    "IMAGE_DIMENSIONS_EXCEEDED",
                    f"图片尺寸 {width}x{height} 超出安全限制",
                )

            probe.verify()
    except ImageValidationError:
        raise
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        OSError,
        SyntaxError,
        ValueError,
    ) as exc:
        raise ImageValidationError(
            "IMAGE_DECODE_FAILED", f"图片结构校验失败: {exc}"
        ) from None

    # verify() 后须重新打开并触发全量像素解码，拦截截断或损坏帧
    try:
        with Image.open(BytesIO(data)) as decoded:
            decoded.load()
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        OSError,
        SyntaxError,
        ValueError,
    ) as exc:
        raise ImageValidationError(
            "IMAGE_DECODE_FAILED", f"图片像素解码失败: {exc}"
        ) from None

    return ValidatedImageInfo(
        content_type=declared_content_type,
        size_bytes=actual_size,
        width=width,
        height=height,
    )
