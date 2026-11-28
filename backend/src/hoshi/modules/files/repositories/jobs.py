from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from hoshi.modules.files.enums import FileAssetStatus, FileJobStatus, FileJobType
from hoshi.modules.files.jobs.policy import MAX_JOB_ATTEMPTS, JobOutcomeKind
from hoshi.modules.files.models import FileAsset, FileJob


@dataclass(frozen=True, slots=True)
class ClaimedFileJob:
    id: int
    asset_id: UUID
    variant_id: UUID | None
    job_type: FileJobType
    attempt_count: int


class FileJobRepository:
    """文件任务原子领取与通用状态回写仓储"""

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

    async def complete_job_succeeded(self, *, job_id: int, attempt_count: int) -> bool:
        """按尝试号保护将任务置为 succeeded"""
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

        # 仅删源成功且启用 CDN 的公开对象登记立即可执行的 purge_variant_cache
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
            # 可重试失败同步延后 available_at 与 next_wakeup_at
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

        # 终态校验失败同步更新对应 pending_validation 资产为 validation_failed
        if job_type == FileJobType.VALIDATE_UPLOAD:
            await self._session.execute(
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
        return True
