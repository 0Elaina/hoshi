from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from hoshi.modules.files.enums import FileAssetStatus, FileJobType


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


class JobWakeupPublisher(Protocol):
    def schedule_wakeup(self, job_id: int, job_type: FileJobType) -> None: ...
