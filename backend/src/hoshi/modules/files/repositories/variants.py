from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Row, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from hoshi.modules.files.constants import FileJobTiming
from hoshi.modules.files.enums import (
    FileAssetStatus,
    FileJobStatus,
    FileJobType,
    FileVariantStatus,
    FileVariantVisibility,
    MediaKind,
)
from hoshi.modules.files.models import FileAsset, FileJob, FileVariant
from hoshi.modules.files.schemas import VariantRecord


@dataclass(frozen=True, slots=True)
class AssetReadinessSnapshot:
    id: UUID
    media_kind: MediaKind
    status: FileAssetStatus


@dataclass(frozen=True, slots=True)
class VariantLocationRow:
    record: VariantRecord
    bucket: str | None
    object_key: str | None


@dataclass(frozen=True, slots=True)
class VariantGenerationSnapshot:
    variant_id: UUID
    asset_id: UUID
    preset_name: str
    preset_revision: int
    visibility: FileVariantVisibility
    variant_status: FileVariantStatus
    media_kind: MediaKind
    asset_status: FileAssetStatus
    original_bucket: str | None
    original_key: str | None


@dataclass(frozen=True, slots=True)
class VariantCleanupSnapshot:
    variant_id: UUID
    asset_id: UUID
    visibility: FileVariantVisibility
    status: FileVariantStatus
    bucket: str | None
    object_key: str | None


def _row_to_variant_record(row: Row[Any]) -> VariantRecord:
    return VariantRecord(
        id=row.id,
        asset_id=row.asset_id,
        preset_name=row.preset_name,
        preset_revision=row.preset_revision,
        visibility=FileVariantVisibility(row.visibility),
        status=FileVariantStatus(row.status),
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        width=row.width,
        height=row.height,
        duration_ms=row.duration_ms,
    )


class FileVariantRepository:
    """文件衍生规格申请、批量查询、撤回以及后台生成/清理写回仓储"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_asset_readiness(
        self, asset_id: UUID
    ) -> AssetReadinessSnapshot | None:
        """读取资产媒体类型与就绪状态"""
        stmt = select(FileAsset.id, FileAsset.media_kind, FileAsset.status).where(
            FileAsset.id == asset_id
        )
        row = (await self._session.execute(stmt)).one_or_none()
        if row is None:
            return None
        return AssetReadinessSnapshot(
            id=row.id,
            media_kind=MediaKind(row.media_kind),
            status=FileAssetStatus(row.status),
        )

    async def try_insert_unavailable_variant(
        self,
        *,
        asset_id: UUID,
        preset_name: str,
        preset_revision: int,
        visibility: FileVariantVisibility,
        now: datetime,
    ) -> VariantRecord | None:
        """基于部分唯一索引尝试插入 unavailable 规格；冲突时返回 None"""
        stmt = (
            pg_insert(FileVariant)
            .values(
                id=uuid4(),
                asset_id=asset_id,
                preset_name=preset_name,
                preset_revision=preset_revision,
                visibility=visibility.value,
                status=FileVariantStatus.UNAVAILABLE.value,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    "asset_id",
                    "preset_name",
                    "preset_revision",
                    "visibility",
                ],
                # 与迁移部分唯一索引 uq_file_variants_active_spec 谓词严格一致
                index_where=text("status <> 'withdrawn'"),
            )
            .returning(
                FileVariant.id,
                FileVariant.asset_id,
                FileVariant.preset_name,
                FileVariant.preset_revision,
                FileVariant.visibility,
                FileVariant.status,
                FileVariant.content_type,
                FileVariant.size_bytes,
                FileVariant.width,
                FileVariant.height,
                FileVariant.duration_ms,
            )
        )
        row = (await self._session.execute(stmt)).one_or_none()
        return _row_to_variant_record(row) if row is not None else None

    async def lock_active_variant(
        self,
        *,
        asset_id: UUID,
        preset_name: str,
        preset_revision: int,
        visibility: FileVariantVisibility,
    ) -> VariantRecord | None:
        """在插入冲突后独立执行 SELECT FOR UPDATE 锁定同元组未撤回规格"""
        stmt = (
            select(
                FileVariant.id,
                FileVariant.asset_id,
                FileVariant.preset_name,
                FileVariant.preset_revision,
                FileVariant.visibility,
                FileVariant.status,
                FileVariant.content_type,
                FileVariant.size_bytes,
                FileVariant.width,
                FileVariant.height,
                FileVariant.duration_ms,
            )
            .where(
                FileVariant.asset_id == asset_id,
                FileVariant.preset_name == preset_name,
                FileVariant.preset_revision == preset_revision,
                FileVariant.visibility == visibility.value,
                FileVariant.status != FileVariantStatus.WITHDRAWN.value,
            )
            .with_for_update()
        )
        row = (await self._session.execute(stmt)).one_or_none()
        return _row_to_variant_record(row) if row is not None else None

    async def try_enqueue_generate_variant_job(
        self, *, asset_id: UUID, variant_id: UUID, now: datetime
    ) -> int | None:
        """按活跃任务部分唯一索引补建 generate_variant，仅真正插入新任务时返回 job_id"""
        next_wakeup = now + timedelta(
            seconds=FileJobTiming.MQ_INITIAL_WAKEUP_DELAY_SECONDS
        )
        stmt = (
            pg_insert(FileJob)
            .values(
                asset_id=asset_id,
                variant_id=variant_id,
                job_type=FileJobType.GENERATE_VARIANT.value,
                status=FileJobStatus.PENDING.value,
                available_at=now,
                next_wakeup_at=next_wakeup,
                attempt_count=0,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(
                index_elements=["variant_id", "job_type"],
                # 与迁移部分唯一索引 uq_file_jobs_active_variant_job 严格一致，历史 failed 保留不冲突
                index_where=text(
                    "variant_id IS NOT NULL AND status IN ('pending', 'running')"
                ),
            )
            .returning(FileJob.id)
        )
        return await self._session.scalar(stmt)

    async def get_variants_by_ids(
        self, variant_ids: Sequence[UUID]
    ) -> list[VariantLocationRow]:
        """单次集合查询批量读取规格状态与对象存储位置"""
        if not variant_ids:
            return []
        stmt = select(
            FileVariant.id,
            FileVariant.asset_id,
            FileVariant.preset_name,
            FileVariant.preset_revision,
            FileVariant.visibility,
            FileVariant.status,
            FileVariant.content_type,
            FileVariant.size_bytes,
            FileVariant.width,
            FileVariant.height,
            FileVariant.duration_ms,
            FileVariant.bucket,
            FileVariant.object_key,
        ).where(FileVariant.id.in_(variant_ids))
        rows = (await self._session.execute(stmt)).all()
        return [
            VariantLocationRow(
                record=_row_to_variant_record(row),
                bucket=row.bucket,
                object_key=row.object_key,
            )
            for row in rows
        ]

    async def withdraw_variants_and_enqueue_cleanup(
        self, *, variant_ids: Sequence[UUID], now: datetime
    ) -> tuple[list[UUID], list[int]]:
        """同一事务内集合 UPDATE RETURNING 置 withdrawn，并为已有物理位置的规格批量补建 cleanup_variant"""
        if not variant_ids:
            return [], []

        withdraw_stmt = (
            update(FileVariant)
            .where(
                FileVariant.id.in_(variant_ids),
                FileVariant.status != FileVariantStatus.WITHDRAWN.value,
            )
            .values(
                status=FileVariantStatus.WITHDRAWN.value,
                updated_at=func.current_timestamp(),
            )
            .returning(
                FileVariant.id,
                FileVariant.asset_id,
                FileVariant.bucket,
                FileVariant.object_key,
            )
        )
        rows = (await self._session.execute(withdraw_stmt)).all()
        if not rows:
            return [], []

        withdrawn_ids = [row.id for row in rows]
        next_wakeup = now + timedelta(
            seconds=FileJobTiming.MQ_INITIAL_WAKEUP_DELAY_SECONDS
        )
        cleanup_values = [
            {
                "asset_id": row.asset_id,
                "variant_id": row.id,
                "job_type": FileJobType.CLEANUP_VARIANT.value,
                "status": FileJobStatus.PENDING.value,
                "available_at": now,
                "next_wakeup_at": next_wakeup,
                "attempt_count": 0,
                "created_at": now,
                "updated_at": now,
            }
            for row in rows
            if row.bucket and row.object_key
        ]
        if not cleanup_values:
            return withdrawn_ids, []

        insert_stmt = (
            pg_insert(FileJob)
            .values(cleanup_values)
            .on_conflict_do_nothing(
                index_elements=["variant_id", "job_type"],
                index_where=text(
                    "variant_id IS NOT NULL AND status IN ('pending', 'running')"
                ),
            )
            .returning(FileJob.id)
        )
        created_job_ids = list((await self._session.scalars(insert_stmt)).all())
        return withdrawn_ids, created_job_ids

    async def get_variant_generation_snapshot(
        self, variant_id: UUID
    ) -> VariantGenerationSnapshot | None:
        """短事务联表读取规格生成所需的规格与原件快照"""
        stmt = (
            select(
                FileVariant.id.label("variant_id"),
                FileVariant.asset_id,
                FileVariant.preset_name,
                FileVariant.preset_revision,
                FileVariant.visibility,
                FileVariant.status.label("variant_status"),
                FileAsset.media_kind,
                FileAsset.status.label("asset_status"),
                FileAsset.original_bucket,
                FileAsset.original_key,
            )
            .join(FileAsset, FileAsset.id == FileVariant.asset_id)
            .where(FileVariant.id == variant_id)
        )
        row = (await self._session.execute(stmt)).one_or_none()
        if row is None:
            return None
        return VariantGenerationSnapshot(
            variant_id=row.variant_id,
            asset_id=row.asset_id,
            preset_name=row.preset_name,
            preset_revision=row.preset_revision,
            visibility=FileVariantVisibility(row.visibility),
            variant_status=FileVariantStatus(row.variant_status),
            media_kind=MediaKind(row.media_kind),
            asset_status=FileAssetStatus(row.asset_status),
            original_bucket=row.original_bucket,
            original_key=row.original_key,
        )

    async def is_variant_still_unavailable(self, variant_id: UUID) -> bool:
        """写入公开桶前二次确认规格仍处于可生成的 unavailable 状态"""
        status_value = await self._session.scalar(
            select(FileVariant.status).where(FileVariant.id == variant_id)
        )
        return status_value == FileVariantStatus.UNAVAILABLE.value

    async def get_variant_cleanup_snapshot(
        self, variant_id: UUID
    ) -> VariantCleanupSnapshot | None:
        """短事务读取删源所需的规格状态与对象位置"""
        stmt = select(
            FileVariant.id,
            FileVariant.asset_id,
            FileVariant.visibility,
            FileVariant.status,
            FileVariant.bucket,
            FileVariant.object_key,
        ).where(FileVariant.id == variant_id)
        row = (await self._session.execute(stmt)).one_or_none()
        if row is None:
            return None
        return VariantCleanupSnapshot(
            variant_id=row.id,
            asset_id=row.asset_id,
            visibility=FileVariantVisibility(row.visibility),
            status=FileVariantStatus(row.status),
            bucket=row.bucket,
            object_key=row.object_key,
        )

    async def complete_generate_variant_success(
        self,
        *,
        job_id: int,
        attempt_count: int,
        variant_id: UUID,
        bucket: str,
        object_key: str,
        content_type: str,
        size_bytes: int,
        width: int | None,
        height: int | None,
    ) -> bool:
        """先锁规格再更新任务，仅当规格仍为 unavailable 且尝试号匹配时登记 ready"""
        # 与规格申请保持一致的加锁顺序：先锁 file_variants 再更新 file_jobs，避免死锁
        variant = await self._session.scalar(
            select(FileVariant).where(FileVariant.id == variant_id).with_for_update()
        )
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
        # 尝试号失效或规格已撤回/就绪时放弃登记，由调用方清理孤儿对象
        if (
            matched_job_id is None
            or variant is None
            or variant.status != FileVariantStatus.UNAVAILABLE.value
        ):
            return False

        await self._session.execute(
            update(FileVariant)
            .where(
                FileVariant.id == variant_id,
                FileVariant.status == FileVariantStatus.UNAVAILABLE.value,
            )
            .values(
                status=FileVariantStatus.READY.value,
                bucket=bucket,
                object_key=object_key,
                content_type=content_type,
                size_bytes=size_bytes,
                width=width,
                height=height,
                updated_at=func.current_timestamp(),
            )
        )
        return True
