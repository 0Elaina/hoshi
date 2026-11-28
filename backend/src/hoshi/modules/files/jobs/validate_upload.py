import asyncio
import logging
from contextlib import suppress
from uuid import uuid4

from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hoshi.modules.files.constants import FileUploadConfig
from hoshi.modules.files.enums import FileAssetStatus, MediaKind
from hoshi.modules.files.jobs.common import (
    classify_botocore_error,
    classify_client_error,
    commit_job_failure,
)
from hoshi.modules.files.jobs.media import validate_image_bytes
from hoshi.modules.files.jobs.policy import (
    JobExecutionResult,
    JobOutcomeKind,
    format_last_error,
    resolve_job_budget,
)
from hoshi.modules.files.object_keys import build_original_key, build_upload_key
from hoshi.modules.files.repositories.assets import FileAssetRepository
from hoshi.modules.files.repositories.jobs import ClaimedFileJob
from hoshi.modules.files.storage.worker import (
    ObjectReadTooLarge,
    WorkerObjectStorage,
    is_object_missing_error,
    is_precondition_failed,
)

logger = logging.getLogger(__name__)


class ValidateUploadHandler:
    """处理 validate_upload：If-Match 读取暂存对象、Pillow 解码校验并写入私有原件"""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        storage: WorkerObjectStorage,
    ) -> None:
        self._session_factory = session_factory
        self._storage = storage

    async def handle(self, claimed: ClaimedFileJob) -> bool:
        try:
            async with self._session_factory() as session, session.begin():
                snapshot = await FileAssetRepository(
                    session
                ).get_asset_validation_snapshot(claimed.asset_id)
        except Exception:
            logger.exception("读取待校验资产快照失败: job_id=%s", claimed.id)
            return False

        if snapshot is None:
            return await commit_job_failure(
                self._session_factory,
                claimed,
                JobExecutionResult(
                    outcome=JobOutcomeKind.PERMANENT_FAILURE,
                    error_code="FILE_ASSET_NOT_FOUND",
                    error_summary="待校验文件资产不存在",
                ),
            )

        if snapshot.status != FileAssetStatus.PENDING_VALIDATION:
            return await commit_job_failure(
                self._session_factory,
                claimed,
                JobExecutionResult(
                    outcome=JobOutcomeKind.PERMANENT_FAILURE,
                    error_code="INVALID_ASSET_STATUS",
                    error_summary=f"资产状态为 {snapshot.status.value}，无法执行校验",
                ),
            )

        if not snapshot.upload_etag:
            return await commit_job_failure(
                self._session_factory,
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
            # 外部 S3 读取、解码与原件落盘全部在数据库事务外受统一运行预算保护
            async with asyncio.timeout(budget.run_timeout_seconds):
                if snapshot.media_kind != MediaKind.IMAGE:
                    result = JobExecutionResult(
                        outcome=JobOutcomeKind.PERMANENT_FAILURE,
                        error_code="UNSUPPORTED_MEDIA_KIND",
                        error_summary=f"暂不支持校验媒体类型 {snapshot.media_kind.value}",
                    )
                else:
                    read_result = await self._storage.get_object_bytes(
                        bucket=self._storage.private_bucket,
                        key=upload_key,
                        if_match=snapshot.upload_etag,
                        max_bytes=FileUploadConfig.IMAGE_MAX_SIZE_BYTES,
                    )
                    if isinstance(read_result, ObjectReadTooLarge):
                        result = JobExecutionResult(
                            outcome=JobOutcomeKind.VALIDATION_REJECTED,
                            error_code="IMAGE_TOO_LARGE",
                            error_summary=(
                                f"对象体积超出允许上限 {read_result.max_bytes} 字节"
                            ),
                        )
                    else:
                        validated = await asyncio.to_thread(
                            validate_image_bytes,
                            read_result,
                            declared_content_type=snapshot.declared_content_type,
                            declared_size_bytes=snapshot.declared_size_bytes,
                        )
                        if isinstance(validated, JobExecutionResult):
                            result = validated
                        else:
                            original_key = build_original_key(
                                snapshot.media_kind, snapshot.id, uuid4()
                            )
                            await self._storage.put_object_bytes(
                                bucket=self._storage.private_bucket,
                                key=original_key,
                                data=read_result,
                                content_type=validated.content_type,
                            )
                            written_original_key = original_key
                            result = JobExecutionResult(
                                outcome=JobOutcomeKind.SUCCEEDED
                            )
        except TimeoutError:
            result = JobExecutionResult(
                outcome=JobOutcomeKind.RETRYABLE_FAILURE,
                error_code="JOB_RUN_TIMEOUT",
                error_summary=f"原件校验超过运行预算 {budget.run_timeout_seconds} 秒",
            )
        except ClientError as exc:
            # S3 If-Match 返回 412 直接永久拒绝资产并记录 UPLOAD_ETAG_MISMATCH
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
            else:
                result = classify_client_error(exc)
        except BotoCoreError as exc:
            result = classify_botocore_error(exc)
        except Exception as exc:
            logger.exception("校验任务发生未预期异常: job_id=%s", claimed.id)
            result = JobExecutionResult(
                outcome=JobOutcomeKind.RETRYABLE_FAILURE,
                error_code=type(exc).__name__,
                error_summary=str(exc),
            )

        if result.outcome == JobOutcomeKind.SUCCEEDED:
            assert written_original_key is not None
            return await self._commit_success(
                claimed=claimed,
                original_key=written_original_key,
                content_type=snapshot.declared_content_type,
                size_bytes=snapshot.declared_size_bytes,
            )

        if result.outcome == JobOutcomeKind.VALIDATION_REJECTED:
            return await self._commit_rejected(claimed, result)

        return await commit_job_failure(self._session_factory, claimed, result)

    async def _commit_success(
        self,
        *,
        claimed: ClaimedFileJob,
        original_key: str,
        content_type: str,
        size_bytes: int,
    ) -> bool:
        try:
            async with self._session_factory() as session, session.begin():
                committed = await FileAssetRepository(
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

    async def _commit_rejected(
        self, claimed: ClaimedFileJob, result: JobExecutionResult
    ) -> bool:
        last_error = format_last_error(result.error_code, result.error_summary)
        try:
            async with self._session_factory() as session, session.begin():
                await FileAssetRepository(session).complete_validate_upload_rejected(
                    job_id=claimed.id,
                    attempt_count=claimed.attempt_count,
                    asset_id=claimed.asset_id,
                    last_error=last_error,
                )
        except Exception:
            logger.exception("提交原件校验拒绝状态失败: job_id=%s", claimed.id)
            return False
        return True
