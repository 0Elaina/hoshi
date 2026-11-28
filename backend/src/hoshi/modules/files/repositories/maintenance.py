from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, case, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from hoshi.modules.files.enums import FileAssetStatus, FileJobStatus, FileJobType
from hoshi.modules.files.jobs.policy import (
    DEFAULT_JOB_BUDGET,
    JOB_BUDGET_POLICIES,
    MAX_JOB_ATTEMPTS,
    RETRY_BACKOFF_SECONDS,
    compute_retry_delay_seconds,
)
from hoshi.modules.files.models import FileAsset, FileJob


@dataclass(frozen=True, slots=True)
class ReclaimSummary:
    requeued_count: int
    failed_count: int


@dataclass(frozen=True, slots=True)
class WakeupJobItem:
    id: int
    job_type: FileJobType


@dataclass(frozen=True, slots=True)
class ClaimedCdnPurgeJob:
    id: int
    variant_id: UUID
    attempt_count: int
    object_key: str | None


class FileMaintenanceRepository:
    """分钟维护循环专用的超时回收、历史清理、MQ 补发与 CDN 批领仓储"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def reclaim_timed_out_jobs(
        self, *, now: datetime, limit: int = 100
    ) -> ReclaimSummary:
        """按统一预算策略回收超时 running 任务，第 3 次超时直接终态失败并同步更新校验资产"""
        # 从同一份 JOB_BUDGET_POLICIES 构造 SQL CASE 阈值，保证领取与回收口径一致
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

        # 利用 ix_file_jobs_running_or_succeeded 扫描超时的 running 行并跳过已锁行
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

        # 终态校验任务与对应 pending_validation 资产在同一事务内集合更新
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
        """按部分索引批量领取待补发 MQ 任务并推迟 next_wakeup_at 3 分钟，保持 updated_at 不变"""
        # 固定谓词与迁移部分索引 ix_file_jobs_pending_mq_wakeup 严格对齐
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
                {"limit": limit, "wakeup_delay_seconds": wakeup_delay_seconds},
            )
        ).all()
        return [
            WakeupJobItem(id=row.id, job_type=FileJobType(row.job_type)) for row in rows
        ]

    async def claim_cdn_purge_batch(
        self, *, limit: int = 30
    ) -> list[ClaimedCdnPurgeJob]:
        """按部分索引 ix_file_jobs_pending_cdn_purge 批量原子领取到期 CDN 清理任务"""
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
                stmt, {"limit": limit, "max_attempts": MAX_JOB_ATTEMPTS}
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

        # 按 attempt_count 分组，确保每条集合 UPDATE 均携带精确尝试号保护
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
