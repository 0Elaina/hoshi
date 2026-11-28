from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class CdnPurgeOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    RETRYABLE_FAILURE = "retryable_failure"
    PERMANENT_FAILURE = "permanent_failure"


@dataclass(frozen=True, slots=True)
class CdnPurgeResult:
    """CDN 批量清理适配器返回的结构化结果"""

    outcome: CdnPurgeOutcome
    retry_after_seconds: int | None = None
    error_code: str | None = None


class CdnPurgeAdapter(Protocol):
    """具体 CDN 供应商接入须实现的批量 URL 清理契约"""

    async def purge_urls(self, urls: Sequence[str]) -> CdnPurgeResult: ...


def build_public_media_url(base_url: str, object_key: str) -> str:
    """将公开媒体根基址与对象键拼接为不可变公开访问 URL"""
    return f"{base_url.rstrip('/')}/{object_key.lstrip('/')}"
