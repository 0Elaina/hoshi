from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from hoshi.modules.files.enums import (
    FileAssetStatus,
    FileJobType,
    FileVariantStatus,
    FileVariantVisibility,
)


@dataclass(frozen=True, slots=True)
class UploadGrant:
    asset_id: UUID
    upload_url: str
    upload_headers: dict[str, str]
    upload_expires_in_seconds: int
    confirm_expires_at: datetime


@dataclass(frozen=True, slots=True)
class UploadConfirmation:
    asset_id: UUID
    status: FileAssetStatus
    confirmed_at: datetime


@dataclass(frozen=True, slots=True)
class VariantRecord:
    """规格申请与状态轮询返回视图"""

    id: UUID
    asset_id: UUID
    preset_name: str
    preset_revision: int
    visibility: FileVariantVisibility
    status: FileVariantStatus
    content_type: str | None
    size_bytes: int | None
    width: int | None
    height: int | None
    duration_ms: int | None


@dataclass(frozen=True, slots=True)
class VariantAccessView:
    """带访问地址的规格批量读取视图（仅 ready 返回非空 url）"""

    variant: VariantRecord
    url: str | None


class JobWakeupPublisher(Protocol):
    def schedule_wakeup(self, job_id: int, job_type: FileJobType) -> None: ...
