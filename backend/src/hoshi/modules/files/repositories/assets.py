from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
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


@dataclass(frozen=True, slots=True)
class AssetValidationSnapshot:
    id: UUID
    media_kind: MediaKind
    status: FileAssetStatus
    declared_content_type: str
    declared_size_bytes: int
    upload_etag: str | None


class FileAssetRepository:
    """文件资产上传登记、确认与原件校验写回仓储"""

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

    async def get_asset_validation_snapshot(
        self, asset_id: UUID
    ) -> AssetValidationSnapshot | None:
        """短事务读取原件校验所需的标量快照"""
        stmt = select(
            FileAsset.id,
            FileAsset.media_kind,
            FileAsset.status,
            FileAsset.declared_content_type,
            FileAsset.declared_size_bytes,
            FileAsset.upload_etag,
        ).where(FileAsset.id == asset_id)
        row = (await self._session.execute(stmt)).one_or_none()
        if row is None:
            return None
        return AssetValidationSnapshot(
            id=row.id,
            media_kind=MediaKind(row.media_kind),
            status=FileAssetStatus(row.status),
            declared_content_type=row.declared_content_type,
            declared_size_bytes=row.declared_size_bytes,
            upload_etag=row.upload_etag,
        )

    async def complete_validate_upload_success(
        self,
        *,
        job_id: int,
        attempt_count: int,
        asset_id: UUID,
        original_bucket: str,
        original_key: str,
        original_content_type: str,
        original_size_bytes: int,
    ) -> bool:
        """按尝试号保护提交校验成功，并在同一事务将资产置为 ready"""
        matched_job_id = await self._session.scalar(
            update(FileJob)
            .where(
                FileJob.id == job_id,
                FileJob.status == FileJobStatus.RUNNING.value,
                FileJob.attempt_count == attempt_count,
            )
            .values(
                status=FileJobStatus.SUCCEEDED.value,
                last_error=None,
                updated_at=func.current_timestamp(),
            )
            .returning(FileJob.id)
        )
        # 尝试号不匹配说明任务已被超时回收或重跑，放弃写回资产
        if matched_job_id is None:
            return False

        await self._session.execute(
            update(FileAsset)
            .where(
                FileAsset.id == asset_id,
                FileAsset.status == FileAssetStatus.PENDING_VALIDATION.value,
            )
            .values(
                status=FileAssetStatus.READY.value,
                original_bucket=original_bucket,
                original_key=original_key,
                original_content_type=original_content_type,
                original_size_bytes=original_size_bytes,
                updated_at=func.current_timestamp(),
            )
        )
        return True

    async def complete_validate_upload_rejected(
        self,
        *,
        job_id: int,
        attempt_count: int,
        asset_id: UUID,
        last_error: str | None,
    ) -> bool:
        """按尝试号保护提交校验拒绝（含 412 ETag 不符与内容非法）"""
        matched_job_id = await self._session.scalar(
            update(FileJob)
            .where(
                FileJob.id == job_id,
                FileJob.status == FileJobStatus.RUNNING.value,
                FileJob.attempt_count == attempt_count,
            )
            .values(
                status=FileJobStatus.FAILED.value,
                last_error=last_error,
                updated_at=func.current_timestamp(),
            )
            .returning(FileJob.id)
        )
        if matched_job_id is None:
            return False

        await self._session.execute(
            update(FileAsset)
            .where(
                FileAsset.id == asset_id,
                FileAsset.status == FileAssetStatus.PENDING_VALIDATION.value,
            )
            .values(
                status=FileAssetStatus.VALIDATION_REJECTED.value,
                updated_at=func.current_timestamp(),
            )
        )
        return True
