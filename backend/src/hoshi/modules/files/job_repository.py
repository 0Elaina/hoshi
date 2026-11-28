from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, case, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from hoshi.modules.files.enums import (
    FileAssetStatus,
    FileJobStatus,
    FileJobType,
    FileVariantStatus,
    FileVariantVisibility,
    MediaKind,
)
from hoshi.modules.files.job_policy import (
    DEFAULT_JOB_BUDGET,
    JOB_BUDGET_POLICIES,
    MAX_JOB_ATTEMPTS,
    RETRY_BACKOFF_SECONDS,
    JobOutcomeKind,
    compute_retry_delay_seconds,
)
from hoshi.modules.files.models import FileAsset, FileJob, FileVariant


@dataclass(frozen=True, slots=True)
class ClaimedFileJob:
    id: int
    asset_id: UUID
    variant_id: UUID | None
    job_type: FileJobType
    attempt_count: int


@dataclass(frozen=True, slots=True)
class AssetValidationSnapshot:
    id: UUID
    media_kind: MediaKind
    status: FileAssetStatus
    declared_content_type: str
    declared_size_bytes: int
    upload_etag: str | None


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


@dataclass(frozen=True, slots=True)
class ClaimedCdnPurgeJob:
    id: int
    variant_id: UUID
    attempt_count: int
    object_key: str | None


@dataclass(frozen=True, slots=True)
class ReclaimSummary:
    requeued_count: int
    failed_count: int


@dataclass(frozen=True, slots=True)
class WakeupJobItem:
    id: int
    job_type: FileJobType


class FileJobRepository:
    """文件后台任务领取、状态回写、维护扫描与 CDN 批领仓储"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def claim_job(
        self,
        *,
        job_id: int,
        allowed_job_types: Sequence[FileJobType],
    ) -> ClaimedFileJob | None:
        """单条 UPDATE RETURNING 原子领取到期 pending 任务"""
        allowed_values = [job_type.value for job_type in allowed_job_types]
        stmt = (
            update(FileJob)
            .where(
                FileJob.id == job_id,
                FileJob.job_type.in_(allowed_values),
                FileJob.status == FileJobStatus.PENDING.value,
                FileJob.available_at <= func.current_timestamp(),
                FileJob.attempt_count < MAX_JOB_ATTEMPTS,
            )
            .values(
                status=FileJobStatus.RUNNING.value,
                attempt_count=FileJob.attempt_count + 1,
                updated_at=func.current_timestamp(),
            )
            .returning(
                FileJob.id,
                FileJob.asset_id,
                FileJob.variant_id,
                FileJob.job_type,
                FileJob.attempt_count,
            )
        )
        row = (await self._session.execute(stmt)).one_or_none()
        if row is None:
            return None
        return ClaimedFileJob(
            id=row.id,
            asset_id=row.asset_id,
            variant_id=row.variant_id,
            job_type=FileJobType(row.job_type),
            attempt_count=row.attempt_count,
        )

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

    async def complete_job_succeeded(self, *, job_id: int, attempt_count: int) -> bool:
        """按尝试号保护将任务置为 succeeded（用于无需再生成的已就绪/已撤回规格）"""
        stmt = (
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
        return (await self._session.scalar(stmt)) is not None

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
        job_stmt = (
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
        matched_job_id = await self._session.scalar(job_stmt)
        if matched_job_id is None:
            return False

        asset_stmt = (
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
        await self._session.execute(asset_stmt)
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
        job_stmt = (
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
        matched_job_id = await self._session.scalar(job_stmt)
        if matched_job_id is None:
            return False

        asset_stmt = (
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
        await self._session.execute(asset_stmt)
        return True

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
        # 与规格申请保持一致的加锁顺序：同时涉及两张表时先锁 file_variants，避免死锁
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
        # 尝试号已失效，或规格已被撤回/已就绪时放弃登记，调用方随后清理孤儿对象
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

    async def complete_cleanup_variant_success(
        self,
        *,
        job_id: int,
        attempt_count: int,
        asset_id: UUID,
        variant_id: UUID,
        enqueue_cdn_purge: bool,
        now: datetime,
    ) -> bool:
        """删源成功后提交清理完成，并在同一事务按需为公开对象登记 purge_variant_cache"""
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
        if matched_job_id is None:
            return False

        # 只有删源成功且启用 CDN 的公开对象，才登记立即可执行的 purge_variant_cache
        if enqueue_cdn_purge:
            await self._session.execute(
                pg_insert(FileJob)
                .values(
                    asset_id=asset_id,
                    variant_id=variant_id,
                    job_type=FileJobType.PURGE_VARIANT_CACHE.value,
                    status=FileJobStatus.PENDING.value,
                    available_at=now,
                    next_wakeup_at=now,
                    attempt_count=0,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing(
                    index_elements=["variant_id", "job_type"],
                    index_where=text(
                        "variant_id IS NOT NULL AND status IN ('pending', 'running')"
                    ),
                )
            )
        return True

    async def complete_job_failure(
        self,
        *,
        job_id: int,
        attempt_count: int,
        job_type: FileJobType,
        asset_id: UUID,
        outcome: JobOutcomeKind,
        last_error: str | None,
        retry_delay_seconds: int | None,
        now: datetime,
    ) -> bool:
        """提交可重试退避或终态失败，终态校验任务同步将资产置为 validation_failed"""
        if (
            outcome == JobOutcomeKind.RETRYABLE_FAILURE
            and retry_delay_seconds is not None
        ):
            next_time = now + timedelta(seconds=retry_delay_seconds)
            retry_stmt = (
                update(FileJob)
                .where(
                    FileJob.id == job_id,
                    FileJob.status == FileJobStatus.RUNNING.value,
                    FileJob.attempt_count == attempt_count,
                )
                .values(
                    status=FileJobStatus.PENDING.value,
                    available_at=next_time,
                    next_wakeup_at=next_time,
                    last_error=last_error,
                    updated_at=func.current_timestamp(),
                )
                .returning(FileJob.id)
            )
            return (await self._session.scalar(retry_stmt)) is not None

        fail_stmt = (
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
        matched_job_id = await self._session.scalar(fail_stmt)
        if matched_job_id is None:
            return False

        if job_type == FileJobType.VALIDATE_UPLOAD:
            asset_stmt = (
                update(FileAsset)
                .where(
                    FileAsset.id == asset_id,
                    FileAsset.status == FileAssetStatus.PENDING_VALIDATION.value,
                )
                .values(
                    status=FileAssetStatus.VALIDATION_FAILED.value,
                    updated_at=func.current_timestamp(),
                )
            )
            await self._session.execute(asset_stmt)
        return True

    async def reclaim_timed_out_jobs(
        self, *, now: datetime, limit: int = 100
    ) -> ReclaimSummary:
        """按统一预算策略回收超时 running 任务，第 3 次超时直接终态失败并同步更新校验资产"""
        specific_whens = [
            (
                (FileJob.job_type == job_type.value)
                & (FileAsset.media_kind == media_kind.value),
                budget.reclaim_after_seconds,
            )
            for (job_type, media_kind), budget in JOB_BUDGET_POLICIES.items()
            if media_kind is not None
        ]
        generic_whens = [
            (FileJob.job_type == job_type.value, budget.reclaim_after_seconds)
            for (job_type, media_kind), budget in JOB_BUDGET_POLICIES.items()
            if media_kind is None
        ]
        reclaim_seconds_expr = case(
            *specific_whens,
            *generic_whens,
            else_=DEFAULT_JOB_BUDGET.reclaim_after_seconds,
        )

        cutoff_expr = func.current_timestamp() - (
            reclaim_seconds_expr * text("INTERVAL '1 second'")
        )
        candidates_stmt = (
            select(
                FileJob.id,
                FileJob.asset_id,
                FileJob.job_type,
                FileJob.attempt_count,
            )
            .join(FileAsset, FileAsset.id == FileJob.asset_id)
            .where(
                FileJob.status == FileJobStatus.RUNNING.value,
                FileJob.updated_at <= cutoff_expr,
            )
            .order_by(FileJob.updated_at, FileJob.id)
            .limit(limit)
            .with_for_update(of=FileJob, skip_locked=True)
        )
        rows = (await self._session.execute(candidates_stmt)).all()
        if not rows:
            return ReclaimSummary(requeued_count=0, failed_count=0)

        requeue_by_delay: dict[int, list[int]] = {}
        terminal_job_ids: list[int] = []
        terminal_validate_asset_ids: list[UUID] = []

        for row in rows:
            if row.attempt_count >= MAX_JOB_ATTEMPTS:
                terminal_job_ids.append(row.id)
                if row.job_type == FileJobType.VALIDATE_UPLOAD.value:
                    terminal_validate_asset_ids.append(row.asset_id)
            else:
                index = max(
                    0, min(row.attempt_count - 1, len(RETRY_BACKOFF_SECONDS) - 1)
                )
                delay = RETRY_BACKOFF_SECONDS[index]
                requeue_by_delay.setdefault(delay, []).append(row.id)

        requeued_count = 0
        for delay, job_ids in requeue_by_delay.items():
            next_time = now + timedelta(seconds=delay)
            await self._session.execute(
                update(FileJob)
                .where(
                    FileJob.id.in_(job_ids),
                    FileJob.status == FileJobStatus.RUNNING.value,
                )
                .values(
                    status=FileJobStatus.PENDING.value,
                    available_at=next_time,
                    next_wakeup_at=next_time,
                    last_error="JOB_TIMEOUT: 任务运行超时已回收重排",
                    updated_at=func.current_timestamp(),
                )
            )
            requeued_count += len(job_ids)

        failed_count = 0
        if terminal_job_ids:
            await self._session.execute(
                update(FileJob)
                .where(
                    FileJob.id.in_(terminal_job_ids),
                    FileJob.status == FileJobStatus.RUNNING.value,
                )
                .values(
                    status=FileJobStatus.FAILED.value,
                    last_error="JOB_TIMEOUT: 任务运行超时达到最大重试次数",
                    updated_at=func.current_timestamp(),
                )
            )
            failed_count = len(terminal_job_ids)

        if terminal_validate_asset_ids:
            await self._session.execute(
                update(FileAsset)
                .where(
                    FileAsset.id.in_(terminal_validate_asset_ids),
                    FileAsset.status == FileAssetStatus.PENDING_VALIDATION.value,
                )
                .values(
                    status=FileAssetStatus.VALIDATION_FAILED.value,
                    updated_at=func.current_timestamp(),
                )
            )

        return ReclaimSummary(requeued_count=requeued_count, failed_count=failed_count)

    async def cleanup_succeeded_job_history(
        self, *, retention_days: int = 30, limit: int = 500
    ) -> int:
        """按 (updated_at, id) 选取最多 500 条超 30 天的 succeeded 历史并单条 DELETE USING 删除"""
        stmt = text(
            """
            DELETE FROM file_jobs
            USING (
                SELECT id
                FROM file_jobs
                WHERE status = 'succeeded'
                  AND updated_at < CURRENT_TIMESTAMP - (:retention_days * INTERVAL '1 day')
                ORDER BY updated_at, id
                LIMIT :limit
            ) AS expired
            WHERE file_jobs.id = expired.id
            """
        )
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                stmt, {"retention_days": retention_days, "limit": limit}
            ),
        )
        return int(result.rowcount or 0)

    async def claim_mq_wakeup_batch(
        self, *, limit: int = 100, wakeup_delay_seconds: int = 180
    ) -> list[WakeupJobItem]:
        """按部分索引批量领取待补发的 MQ 任务并推迟 next_wakeup_at 3 分钟，保持 updated_at 不变"""
        stmt = text(
            """
            WITH due AS (
                SELECT id
                FROM file_jobs
                WHERE status = 'pending'
                  AND job_type <> 'purge_variant_cache'
                  AND next_wakeup_at <= CURRENT_TIMESTAMP
                ORDER BY next_wakeup_at, id
                LIMIT :limit
                FOR UPDATE SKIP LOCKED
            )
            UPDATE file_jobs
            SET next_wakeup_at = CURRENT_TIMESTAMP + (:wakeup_delay_seconds * INTERVAL '1 second')
            FROM due
            WHERE file_jobs.id = due.id
            RETURNING file_jobs.id, file_jobs.job_type
            """
        )
        rows = (
            await self._session.execute(
                stmt,
                {
                    "limit": limit,
                    "wakeup_delay_seconds": wakeup_delay_seconds,
                },
            )
        ).all()
        return [
            WakeupJobItem(id=row.id, job_type=FileJobType(row.job_type)) for row in rows
        ]

    async def claim_cdn_purge_batch(
        self, *, limit: int = 30
    ) -> list[ClaimedCdnPurgeJob]:
        """按部分索引 ix_file_jobs_pending_cdn_purge 批量原子领取到期 CDN 清理任务"""
        # 固定谓词与迁移部分索引完全一致，领取规则与普通任务共用最大尝试次数约束
        stmt = text(
            """
            WITH due AS (
                SELECT id
                FROM file_jobs
                WHERE status = 'pending'
                  AND job_type = 'purge_variant_cache'
                  AND available_at <= CURRENT_TIMESTAMP
                  AND attempt_count < :max_attempts
                ORDER BY available_at, id
                LIMIT :limit
                FOR UPDATE SKIP LOCKED
            ),
            claimed AS (
                UPDATE file_jobs
                SET status = 'running',
                    attempt_count = file_jobs.attempt_count + 1,
                    updated_at = CURRENT_TIMESTAMP
                FROM due
                WHERE file_jobs.id = due.id
                RETURNING file_jobs.id, file_jobs.variant_id, file_jobs.attempt_count
            )
            SELECT claimed.id, claimed.variant_id, claimed.attempt_count, fv.object_key
            FROM claimed
            JOIN file_variants AS fv ON fv.id = claimed.variant_id
            ORDER BY claimed.id
            """
        )
        rows = (
            await self._session.execute(
                stmt,
                {"limit": limit, "max_attempts": MAX_JOB_ATTEMPTS},
            )
        ).all()
        return [
            ClaimedCdnPurgeJob(
                id=row.id,
                variant_id=row.variant_id,
                attempt_count=row.attempt_count,
                object_key=row.object_key,
            )
            for row in rows
        ]

    async def complete_cdn_purge_batch(
        self,
        *,
        jobs: Sequence[ClaimedCdnPurgeJob],
        outcome: str,
        last_error: str | None,
        retry_after_seconds: int | None,
        now: datetime,
    ) -> None:
        """按 (status='running', attempt_count) 批量回写 CDN 清理批次结果"""
        if not jobs:
            return

        # 按 attempt_count 分组，保持每条集合 UPDATE 都严格带尝试号保护
        ids_by_attempt: dict[int, list[int]] = {}
        for job in jobs:
            ids_by_attempt.setdefault(job.attempt_count, []).append(job.id)

        for attempt_count, job_ids in ids_by_attempt.items():
            if outcome == "succeeded":
                await self._session.execute(
                    update(FileJob)
                    .where(
                        FileJob.id.in_(job_ids),
                        FileJob.status == FileJobStatus.RUNNING.value,
                        FileJob.attempt_count == attempt_count,
                    )
                    .values(
                        status=FileJobStatus.SUCCEEDED.value,
                        last_error=None,
                        updated_at=func.current_timestamp(),
                    )
                )
                continue

            retry_delay = (
                compute_retry_delay_seconds(
                    attempt_count, retry_after_seconds=retry_after_seconds
                )
                if outcome == "retryable_failure"
                else None
            )
            if retry_delay is not None:
                next_time = now + timedelta(seconds=retry_delay)
                # 退避时间取普通退避与上游 Retry-After 的较晚值
                await self._session.execute(
                    update(FileJob)
                    .where(
                        FileJob.id.in_(job_ids),
                        FileJob.status == FileJobStatus.RUNNING.value,
                        FileJob.attempt_count == attempt_count,
                    )
                    .values(
                        status=FileJobStatus.PENDING.value,
                        available_at=next_time,
                        next_wakeup_at=next_time,
                        last_error=last_error,
                        updated_at=func.current_timestamp(),
                    )
                )
            else:
                await self._session.execute(
                    update(FileJob)
                    .where(
                        FileJob.id.in_(job_ids),
                        FileJob.status == FileJobStatus.RUNNING.value,
                        FileJob.attempt_count == attempt_count,
                    )
                    .values(
                        status=FileJobStatus.FAILED.value,
                        last_error=last_error,
                        updated_at=func.current_timestamp(),
                    )
                )
