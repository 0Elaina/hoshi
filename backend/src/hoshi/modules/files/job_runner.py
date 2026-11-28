import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from uuid import uuid4

from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hoshi.modules.files.constants import FileUploadConfig
from hoshi.modules.files.enums import FileAssetStatus, FileJobType, MediaKind
from hoshi.modules.files.job_policy import (
    JobExecutionResult,
    JobOutcomeKind,
    compute_retry_delay_seconds,
    format_last_error,
    resolve_job_budget,
)
from hoshi.modules.files.job_repository import ClaimedFileJob, FileJobRepository
from hoshi.modules.files.media_processors import (
    ImageValidationError,
    validate_image_bytes,
)
from hoshi.modules.files.object_keys import build_original_key, build_upload_key
from hoshi.modules.files.worker_storage import (
    ObjectTooLargeError,
    WorkerObjectStorage,
    is_object_missing_error,
    is_precondition_failed,
    is_retryable_storage_error,
)
from hoshi.shared.utils.time_utils import utc_now

logger = logging.getLogger(__name__)

type JobHandler = Callable[[ClaimedFileJob], Awaitable[bool]]


class FileJobRunner:
    """文件任务统一执行器：短事务领取、事务外外部 I/O、按尝试号保护写回后再 ACK"""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        storage: WorkerObjectStorage,
        extra_handlers: dict[FileJobType, JobHandler] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._storage = storage
        self._extra_handlers: dict[FileJobType, JobHandler] = dict(extra_handlers or {})

    async def process_job_id(
        self, *, job_id: int, allowed_job_types: Sequence[FileJobType]
    ) -> bool:
        """处理单个唤醒 job_id；返回 True 表示可安全 ACK，False 表示保留重投"""
        try:
            async with self._session_factory() as session, session.begin():
                claimed = await FileJobRepository(session).claim_job(
                    job_id=job_id,
                    allowed_job_types=allowed_job_types,
                )
        except Exception:
            # 数据库领取阶段异常时不 ACK，保留 RabbitMQ 重投机会
            logger.exception("领取文件任务失败: job_id=%s", job_id)
            return False

        # 零行命中（已处理、未到期、已被其他 Worker 领取或类型不符）直接 ACK
        if claimed is None:
            return True

        if claimed.job_type == FileJobType.VALIDATE_UPLOAD:
            return await self._run_validate_upload(claimed)

        extra_handler = self._extra_handlers.get(claimed.job_type)
        if extra_handler is not None:
            return await extra_handler(claimed)

        # 未注册处理器的任务类型记永久失败并落库
        return await self._commit_failure(
            claimed,
            JobExecutionResult(
                outcome=JobOutcomeKind.PERMANENT_FAILURE,
                error_code="UNSUPPORTED_JOB_TYPE",
                error_summary=f"未注册任务处理器: {claimed.job_type.value}",
            ),
        )

    async def _run_validate_upload(self, claimed: ClaimedFileJob) -> bool:
        """执行上传暂存对象的 If-Match 读取、图片解码校验与私有原件落盘"""
        try:
            async with self._session_factory() as session, session.begin():
                snapshot = await FileJobRepository(
                    session
                ).get_asset_validation_snapshot(claimed.asset_id)
        except Exception:
            logger.exception("读取待校验资产快照失败: job_id=%s", claimed.id)
            return False

        if snapshot is None:
            return await self._commit_failure(
                claimed,
                JobExecutionResult(
                    outcome=JobOutcomeKind.PERMANENT_FAILURE,
                    error_code="FILE_ASSET_NOT_FOUND",
                    error_summary="待校验文件资产不存在",
                ),
            )

        # 资产已非 pending_validation（如人工介入或异常状态）直接以永久失败收口
        if snapshot.status != FileAssetStatus.PENDING_VALIDATION:
            return await self._commit_failure(
                claimed,
                JobExecutionResult(
                    outcome=JobOutcomeKind.PERMANENT_FAILURE,
                    error_code="INVALID_ASSET_STATUS",
                    error_summary=f"资产状态为 {snapshot.status.value}，无法执行校验",
                ),
            )

        if not snapshot.upload_etag:
            return await self._commit_failure(
                claimed,
                JobExecutionResult(
                    outcome=JobOutcomeKind.PERMANENT_FAILURE,
                    error_code="MISSING_UPLOAD_ETAG",
                    error_summary="待校验资产缺少 upload_etag",
                ),
            )

        budget = resolve_job_budget(claimed.job_type, snapshot.media_kind)
        upload_key = build_upload_key(snapshot.id)
        written_original_key: str | None = None

        try:
            # 外部 S3 读写与 Pillow 解码全部在事务外并受统一运行预算约束
            async with asyncio.timeout(budget.run_timeout_seconds):
                if snapshot.media_kind != MediaKind.IMAGE:
                    result = JobExecutionResult(
                        outcome=JobOutcomeKind.PERMANENT_FAILURE,
                        error_code="UNSUPPORTED_MEDIA_KIND",
                        error_summary=f"暂不支持校验媒体类型 {snapshot.media_kind.value}",
                    )
                else:
                    raw_bytes = await self._storage.get_object_bytes(
                        bucket=self._storage.private_bucket,
                        key=upload_key,
                        if_match=snapshot.upload_etag,
                        max_bytes=FileUploadConfig.IMAGE_MAX_SIZE_BYTES,
                    )
                    validated = await asyncio.to_thread(
                        validate_image_bytes,
                        raw_bytes,
                        declared_content_type=snapshot.declared_content_type,
                        declared_size_bytes=snapshot.declared_size_bytes,
                    )
                    original_key = build_original_key(
                        snapshot.media_kind, snapshot.id, uuid4()
                    )
                    await self._storage.put_object_bytes(
                        bucket=self._storage.private_bucket,
                        key=original_key,
                        data=raw_bytes,
                        content_type=validated.content_type,
                    )
                    written_original_key = original_key
                    result = JobExecutionResult(outcome=JobOutcomeKind.SUCCEEDED)
        except TimeoutError:
            result = JobExecutionResult(
                outcome=JobOutcomeKind.RETRYABLE_FAILURE,
                error_code="JOB_RUN_TIMEOUT",
                error_summary=f"原件校验超过运行预算 {budget.run_timeout_seconds} 秒",
            )
        except ObjectTooLargeError as exc:
            result = JobExecutionResult(
                outcome=JobOutcomeKind.VALIDATION_REJECTED,
                error_code="IMAGE_TOO_LARGE",
                error_summary=str(exc),
            )
        except ImageValidationError as exc:
            result = JobExecutionResult(
                outcome=JobOutcomeKind.VALIDATION_REJECTED,
                error_code=exc.error_code,
                error_summary=exc.summary,
            )
        except ClientError as exc:
            # S3 If-Match 返回 412 表示暂存对象已被替换或篡改，直接永久拒绝该资产
            if is_precondition_failed(exc):
                result = JobExecutionResult(
                    outcome=JobOutcomeKind.VALIDATION_REJECTED,
                    error_code="UPLOAD_ETAG_MISMATCH",
                    error_summary="暂存对象 ETag 与确认记录不符",
                )
            elif is_object_missing_error(exc):
                result = JobExecutionResult(
                    outcome=JobOutcomeKind.VALIDATION_REJECTED,
                    error_code="UPLOAD_OBJECT_MISSING",
                    error_summary="暂存对象不存在",
                )
            elif is_retryable_storage_error(exc):
                err_code = str(
                    (exc.response.get("Error") or {}).get("Code") or "STORAGE_RETRYABLE"
                )
                result = JobExecutionResult(
                    outcome=JobOutcomeKind.RETRYABLE_FAILURE,
                    error_code=err_code,
                    error_summary="对象存储暂态故障",
                )
            else:
                err_code = str(
                    (exc.response.get("Error") or {}).get("Code") or "STORAGE_ERROR"
                )
                result = JobExecutionResult(
                    outcome=JobOutcomeKind.PERMANENT_FAILURE,
                    error_code=err_code,
                    error_summary="对象存储返回不可重试错误",
                )
        except BotoCoreError as exc:
            outcome = (
                JobOutcomeKind.RETRYABLE_FAILURE
                if is_retryable_storage_error(exc)
                else JobOutcomeKind.PERMANENT_FAILURE
            )
            result = JobExecutionResult(
                outcome=outcome,
                error_code=type(exc).__name__,
                error_summary=str(exc),
            )
        except Exception as exc:
            logger.exception("校验任务发生未预期异常: job_id=%s", claimed.id)
            result = JobExecutionResult(
                outcome=JobOutcomeKind.RETRYABLE_FAILURE,
                error_code=type(exc).__name__,
                error_summary=str(exc),
            )

        if result.outcome == JobOutcomeKind.SUCCEEDED:
            assert written_original_key is not None
            return await self._commit_validate_success(
                claimed=claimed,
                original_key=written_original_key,
                content_type=snapshot.declared_content_type,
                size_bytes=snapshot.declared_size_bytes,
            )

        if result.outcome == JobOutcomeKind.VALIDATION_REJECTED:
            return await self._commit_validate_rejected(claimed, result)

        return await self._commit_failure(claimed, result)

    async def _commit_validate_success(
        self,
        *,
        claimed: ClaimedFileJob,
        original_key: str,
        content_type: str,
        size_bytes: int,
    ) -> bool:
        try:
            async with self._session_factory() as session, session.begin():
                committed = await FileJobRepository(
                    session
                ).complete_validate_upload_success(
                    job_id=claimed.id,
                    attempt_count=claimed.attempt_count,
                    asset_id=claimed.asset_id,
                    original_bucket=self._storage.private_bucket,
                    original_key=original_key,
                    original_content_type=content_type,
                    original_size_bytes=size_bytes,
                )
        except Exception:
            logger.exception("提交原件校验成功状态失败: job_id=%s", claimed.id)
            return False

        # 迟到 Worker 未能登记原件时尽力清理自己刚写入的孤儿对象
        if not committed:
            with suppress(Exception):
                await self._storage.delete_object_if_exists(
                    bucket=self._storage.private_bucket,
                    key=original_key,
                )
        return True

    async def _commit_validate_rejected(
        self, claimed: ClaimedFileJob, result: JobExecutionResult
    ) -> bool:
        last_error = format_last_error(result.error_code, result.error_summary)
        try:
            async with self._session_factory() as session, session.begin():
                await FileJobRepository(session).complete_validate_upload_rejected(
                    job_id=claimed.id,
                    attempt_count=claimed.attempt_count,
                    asset_id=claimed.asset_id,
                    last_error=last_error,
                )
        except Exception:
            logger.exception("提交原件校验拒绝状态失败: job_id=%s", claimed.id)
            return False
        return True

    async def _commit_failure(
        self, claimed: ClaimedFileJob, result: JobExecutionResult
    ) -> bool:
        retry_delay = (
            compute_retry_delay_seconds(
                claimed.attempt_count,
                retry_after_seconds=result.retry_after_seconds,
            )
            if result.outcome == JobOutcomeKind.RETRYABLE_FAILURE
            else None
        )
        last_error = format_last_error(result.error_code, result.error_summary)
        try:
            async with self._session_factory() as session, session.begin():
                await FileJobRepository(session).complete_job_failure(
                    job_id=claimed.id,
                    attempt_count=claimed.attempt_count,
                    job_type=claimed.job_type,
                    asset_id=claimed.asset_id,
                    outcome=result.outcome,
                    last_error=last_error,
                    retry_delay_seconds=retry_delay,
                    now=utc_now(),
                )
        except Exception:
            logger.exception("提交任务失败/退避状态失败: job_id=%s", claimed.id)
            return False
        return True
