from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hoshi.modules.files.enums import (
    FileAssetStatus,
    FileJobStatus,
    FileJobType,
    MediaKind,
)
from hoshi.modules.files.models import FileAsset, FileJob


@dataclass(frozen=True, slots=True)
class AssetConfirmSnapshot:
    id: UUID
    status: FileAssetStatus
    declared_content_type: str
    declared_size_bytes: int
    confirm_expires_at: datetime
    confirmed_at: datetime | None


class FileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_pending_asset(
        self,
        *,
        asset_id: UUID,
        owner_account_id: int,
        media_kind: MediaKind,
        declared_content_type: str,
        declared_size_bytes: int,
        confirm_expires_at: datetime,
        now: datetime,
    ) -> FileAsset:
        """写入待上传状态的文件资产记录"""
        asset = FileAsset(
            id=asset_id,
            owner_account_id=owner_account_id,
            media_kind=media_kind.value,
            status=FileAssetStatus.PENDING_UPLOAD.value,
            declared_content_type=declared_content_type,
            declared_size_bytes=declared_size_bytes,
            confirm_expires_at=confirm_expires_at,
            created_at=now,
            updated_at=now,
        )
        self._session.add(asset)
        await self._session.flush()
        return asset

    async def get_asset_confirm_snapshot(
        self, *, asset_id: UUID, owner_account_id: int
    ) -> AssetConfirmSnapshot | None:
        """按资产 ID 与归属账号读取确认前所需的标量快照"""
        stmt = select(
            FileAsset.id,
            FileAsset.status,
            FileAsset.declared_content_type,
            FileAsset.declared_size_bytes,
            FileAsset.confirm_expires_at,
            FileAsset.confirmed_at,
        ).where(
            FileAsset.id == asset_id,
            FileAsset.owner_account_id == owner_account_id,
        )
        row = (await self._session.execute(stmt)).one_or_none()
        if row is None:
            return None
        return AssetConfirmSnapshot(
            id=row.id,
            status=FileAssetStatus(row.status),
            declared_content_type=row.declared_content_type,
            declared_size_bytes=row.declared_size_bytes,
            confirm_expires_at=row.confirm_expires_at,
            confirmed_at=row.confirmed_at,
        )

    async def get_asset_for_update(
        self, *, asset_id: UUID, owner_account_id: int
    ) -> FileAsset | None:
        """按资产 ID 与归属账号加行锁查询资产记录"""
        stmt = (
            select(FileAsset)
            .where(
                FileAsset.id == asset_id,
                FileAsset.owner_account_id == owner_account_id,
            )
            .with_for_update()
        )
        return await self._session.scalar(stmt)

    async def create_validate_upload_job(
        self,
        *,
        asset_id: UUID,
        available_at: datetime,
        next_wakeup_at: datetime,
        now: datetime,
    ) -> int:
        """登记待执行的上传校验任务并返回任务 ID"""
        job = FileJob(
            asset_id=asset_id,
            variant_id=None,
            job_type=FileJobType.VALIDATE_UPLOAD.value,
            status=FileJobStatus.PENDING.value,
            available_at=available_at,
            next_wakeup_at=next_wakeup_at,
            attempt_count=0,
            created_at=now,
            updated_at=now,
        )
        self._session.add(job)
        await self._session.flush()
        return job.id
