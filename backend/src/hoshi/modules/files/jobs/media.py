from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from hoshi.modules.files.constants import FileUploadConfig
from hoshi.modules.files.enums import ImagePreset, MediaFormat, MediaKind

# 图片解码安全阈值，防范解压炸弹与异常超高分辨率
MAX_IMAGE_PIXELS = 25_000_000
MAX_IMAGE_DIMENSION = 8192


@dataclass(frozen=True, slots=True)
class ValidatedImageInfo:
    content_type: str
    size_bytes: int
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class RenderedImageVariant:
    """图片规格渲染输出产物"""

    data: bytes
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


def render_image_variant(
    raw_bytes: bytes, *, preset: ImagePreset
) -> RenderedImageVariant:
    """按已登记图片规格对私有原件执行 EXIF 纠正、元数据剥离与统一编码"""
    try:
        with Image.open(BytesIO(raw_bytes)) as opened:
            # 纠正 EXIF 旋转方向并强制加载像素
            transposed = ImageOps.exif_transpose(opened)
            width, height = transposed.size
            if (
                width <= 0
                or height <= 0
                or width > MAX_IMAGE_DIMENSION
                or height > MAX_IMAGE_DIMENSION
                or width * height > MAX_IMAGE_PIXELS
            ):
                raise ImageValidationError(
                    "IMAGE_DIMENSIONS_EXCEEDED",
                    f"原图尺寸 {width}x{height} 超出渲染安全限制",
                )

            # 统一色彩空间：保留透明通道或转为 RGB，避免调色板/CMYK 编码失败
            has_alpha = (
                "A" in transposed.getbands() or "transparency" in transposed.info
            )
            if preset.output_format == MediaFormat.JPEG:
                normalized = transposed.convert("RGB")
            else:
                normalized = transposed.convert("RGBA" if has_alpha else "RGB")

            # 重新编码写入干净字节缓冲，天然剥离 EXIF/XMP/IPTC 元数据
            output = BytesIO()
            save_kwargs: dict[str, int | bool] = {}
            if preset.output_format in (MediaFormat.WEBP, MediaFormat.JPEG):
                save_kwargs["quality"] = preset.quality
            normalized.save(
                output,
                format=preset.output_format.format_name,
                **save_kwargs,
            )
            encoded = output.getvalue()
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
            "IMAGE_RENDER_FAILED", f"图片规格渲染失败: {exc}"
        ) from None

    return RenderedImageVariant(
        data=encoded,
        content_type=preset.output_format.mime_type,
        size_bytes=len(encoded),
        width=width,
        height=height,
    )
