import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from uuid import uuid4

from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hoshi.modules.files.constants import FileUploadConfig
from hoshi.modules.files.enums import (
    FileAssetStatus,
    FileJobType,
    FileVariantStatus,
    FileVariantVisibility,
    ImagePreset,
    MediaKind,
    lookup_variant_preset,
)
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
    render_image_variant,
    validate_image_bytes,
)
from hoshi.modules.files.object_keys import (
    build_original_key,
    build_upload_key,
    build_variant_key,
)
from hoshi.modules.files.worker_storage import (
    ObjectTooLargeError,
    WorkerObjectStorage,
    is_object_missing_error,
    is_precondition_failed,
    is_retryable_storage_error,
)
from hoshi.shared.utils.time_utils import utc_now

logger = logging.getLogger(__name__)

# 私有与公开衍生物写入 S3 时附带的 Cache-Control 策略
PRIVATE_VARIANT_CACHE_CONTROL = "private, max-age=300"
PUBLIC_VARIANT_CACHE_CONTROL = "public, max-age=300, s-maxage=86400"

type JobHandler = Callable[[ClaimedFileJob], Awaitable[bool]]


class FileJobRunner:
    """文件任务统一执行器：短事务领取、事务外外部 I/O、按尝试号保护写回后再 ACK"""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        storage: WorkerObjectStorage,
        cdn_purge_enabled: bool = False,
        extra_handlers: dict[FileJobType, JobHandler] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._storage = storage
        self._cdn_purge_enabled = cdn_purge_enabled
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
            logger.exception("领取文件任务失败: job_id=%s", job_id)
            return False

        # 零行命中（已处理、未到期、已被其他 Worker 领取或类型不符）直接 ACK
        if claimed is None:
            return True

        if claimed.job_type == FileJobType.VALIDATE_UPLOAD:
            return await self._run_validate_upload(claimed)
        if claimed.job_type == FileJobType.GENERATE_VARIANT:
            return await self._run_generate_variant(claimed)
        if claimed.job_type == FileJobType.CLEANUP_VARIANT:
            return await self._run_cleanup_variant(claimed)

        extra_handler = self._extra_handlers.get(claimed.job_type)
        if extra_handler is not None:
            return await extra_handler(claimed)

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
                result = self._classify_client_error(exc)
        except BotoCoreError as exc:
            result = self._classify_botocore_error(exc)
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

    async def _run_generate_variant(self, claimed: ClaimedFileJob) -> bool:
        """从私有原件渲染衍生规格，公开写前二次复核状态，提交时先锁规格再写回"""
        if claimed.variant_id is None:
            return await self._commit_failure(
                claimed,
                JobExecutionResult(
                    outcome=JobOutcomeKind.PERMANENT_FAILURE,
                    error_code="MISSING_VARIANT_ID",
                    error_summary="规格生成任务缺少 variant_id",
                ),
            )

        try:
            async with self._session_factory() as session, session.begin():
                snapshot = await FileJobRepository(
                    session
                ).get_variant_generation_snapshot(claimed.variant_id)
        except Exception:
            logger.exception("读取规格生成快照失败: job_id=%s", claimed.id)
            return False

        if snapshot is None:
            return await self._commit_failure(
                claimed,
                JobExecutionResult(
                    outcome=JobOutcomeKind.PERMANENT_FAILURE,
                    error_code="FILE_VARIANT_NOT_FOUND",
                    error_summary="目标规格记录不存在",
                ),
            )

        # 规格已就绪或已撤回时无需再生成，直接按成功结束任务
        if snapshot.variant_status != FileVariantStatus.UNAVAILABLE:
            return await self._commit_job_succeeded(claimed)

        if (
            snapshot.asset_status != FileAssetStatus.READY
            or not snapshot.original_bucket
            or not snapshot.original_key
        ):
            return await self._commit_failure(
                claimed,
                JobExecutionResult(
                    outcome=JobOutcomeKind.PERMANENT_FAILURE,
                    error_code="ASSET_ORIGINAL_UNAVAILABLE",
                    error_summary="关联原件未就绪或缺少物理位置",
                ),
            )

        preset = lookup_variant_preset(
            snapshot.media_kind, snapshot.preset_name, snapshot.preset_revision
        )
        if not isinstance(preset, ImagePreset):
            return await self._commit_failure(
                claimed,
                JobExecutionResult(
                    outcome=JobOutcomeKind.PERMANENT_FAILURE,
                    error_code="UNSUPPORTED_VARIANT_PRESET",
                    error_summary=f"未支持的图片规格: {snapshot.preset_name}:v{snapshot.preset_revision}",
                ),
            )

        budget = resolve_job_budget(claimed.job_type, snapshot.media_kind)
        target_bucket = (
            self._storage.public_bucket
            if snapshot.visibility == FileVariantVisibility.PUBLIC
            else self._storage.private_bucket
        )
        cache_control = (
            PUBLIC_VARIANT_CACHE_CONTROL
            if snapshot.visibility == FileVariantVisibility.PUBLIC
            else PRIVATE_VARIANT_CACHE_CONTROL
        )
        target_key = build_variant_key(snapshot.asset_id, preset, uuid4())

        rendered_content_type: str | None = None
        rendered_size_bytes: int | None = None
        rendered_width: int | None = None
        rendered_height: int | None = None
        skipped_before_write = False

        try:
            async with asyncio.timeout(budget.run_timeout_seconds):
                raw_bytes = await self._storage.get_object_bytes(
                    bucket=snapshot.original_bucket,
                    key=snapshot.original_key,
                    max_bytes=FileUploadConfig.IMAGE_MAX_SIZE_BYTES,
                )
                rendered = await asyncio.to_thread(
                    render_image_variant, raw_bytes, preset=preset
                )

                # 写入公开桶前二次确认规格未被撤回，防止已撤回产物进入匿名可读公开桶
                if snapshot.visibility == FileVariantVisibility.PUBLIC:
                    async with self._session_factory() as session, session.begin():
                        still_valid = await FileJobRepository(
                            session
                        ).is_variant_still_unavailable(snapshot.variant_id)
                    if not still_valid:
                        skipped_before_write = True
                        result = JobExecutionResult(outcome=JobOutcomeKind.SUCCEEDED)
                    else:
                        await self._storage.put_object_bytes(
                            bucket=target_bucket,
                            key=target_key,
                            data=rendered.data,
                            content_type=rendered.content_type,
                            cache_control=cache_control,
                        )
                        rendered_content_type = rendered.content_type
                        rendered_size_bytes = rendered.size_bytes
                        rendered_width = rendered.width
                        rendered_height = rendered.height
                        result = JobExecutionResult(outcome=JobOutcomeKind.SUCCEEDED)
                else:
                    await self._storage.put_object_bytes(
                        bucket=target_bucket,
                        key=target_key,
                        data=rendered.data,
                        content_type=rendered.content_type,
                        cache_control=cache_control,
                    )
                    rendered_content_type = rendered.content_type
                    rendered_size_bytes = rendered.size_bytes
                    rendered_width = rendered.width
                    rendered_height = rendered.height
                    result = JobExecutionResult(outcome=JobOutcomeKind.SUCCEEDED)
        except TimeoutError:
            result = JobExecutionResult(
                outcome=JobOutcomeKind.RETRYABLE_FAILURE,
                error_code="JOB_RUN_TIMEOUT",
                error_summary=f"规格生成超过运行预算 {budget.run_timeout_seconds} 秒",
            )
        except (ObjectTooLargeError, ImageValidationError) as exc:
            error_code = (
                exc.error_code
                if isinstance(exc, ImageValidationError)
                else "ORIGINAL_TOO_LARGE"
            )
            result = JobExecutionResult(
                outcome=JobOutcomeKind.PERMANENT_FAILURE,
                error_code=error_code,
                error_summary=str(exc),
            )
        except ClientError as exc:
            result = self._classify_client_error(exc)
        except BotoCoreError as exc:
            result = self._classify_botocore_error(exc)
        except Exception as exc:
            logger.exception("规格生成发生未预期异常: job_id=%s", claimed.id)
            result = JobExecutionResult(
                outcome=JobOutcomeKind.RETRYABLE_FAILURE,
                error_code=type(exc).__name__,
                error_summary=str(exc),
            )

        if result.outcome != JobOutcomeKind.SUCCEEDED:
            return await self._commit_failure(claimed, result)

        if skipped_before_write:
            return await self._commit_job_succeeded(claimed)

        assert rendered_content_type is not None
        assert rendered_size_bytes is not None

        try:
            async with self._session_factory() as session, session.begin():
                registered = await FileJobRepository(
                    session
                ).complete_generate_variant_success(
                    job_id=claimed.id,
                    attempt_count=claimed.attempt_count,
                    variant_id=snapshot.variant_id,
                    bucket=target_bucket,
                    object_key=target_key,
                    content_type=rendered_content_type,
                    size_bytes=rendered_size_bytes,
                    width=rendered_width,
                    height=rendered_height,
                )
        except Exception:
            logger.exception("提交规格生成成功状态失败: job_id=%s", claimed.id)
            return False

        # 迟到 Worker 或写完后规格被撤回时，尽力删除自己刚写入的孤儿对象
        if not registered:
            with suppress(Exception):
                await self._storage.delete_object_if_exists(
                    bucket=target_bucket,
                    key=target_key,
                )
        return True

    async def _run_cleanup_variant(self, claimed: ClaimedFileJob) -> bool:
        """删除已撤回规格的对象源；仅删源成功后在同一事务按需登记 purge_variant_cache"""
        if claimed.variant_id is None:
            return await self._commit_failure(
                claimed,
                JobExecutionResult(
                    outcome=JobOutcomeKind.PERMANENT_FAILURE,
                    error_code="MISSING_VARIANT_ID",
                    error_summary="对象清理任务缺少 variant_id",
                ),
            )

        try:
            async with self._session_factory() as session, session.begin():
                snapshot = await FileJobRepository(
                    session
                ).get_variant_cleanup_snapshot(claimed.variant_id)
        except Exception:
            logger.exception("读取待清理规格快照失败: job_id=%s", claimed.id)
            return False

        if snapshot is None:
            return await self._commit_failure(
                claimed,
                JobExecutionResult(
                    outcome=JobOutcomeKind.PERMANENT_FAILURE,
                    error_code="FILE_VARIANT_NOT_FOUND",
                    error_summary="待清理规格不存在",
                ),
            )

        # 防御性检查：严禁删除非 withdrawn 规格的物理对象
        if snapshot.status != FileVariantStatus.WITHDRAWN:
            return await self._commit_failure(
                claimed,
                JobExecutionResult(
                    outcome=JobOutcomeKind.PERMANENT_FAILURE,
                    error_code="VARIANT_NOT_WITHDRAWN",
                    error_summary=f"规格状态为 {snapshot.status.value}，拒绝删除源对象",
                ),
            )

        # 未曾落盘对象的已撤回规格直接成功收口，不登记 CDN 清理
        if not snapshot.bucket or not snapshot.object_key:
            return await self._commit_job_succeeded(claimed)

        budget = resolve_job_budget(claimed.job_type)
        try:
            async with asyncio.timeout(budget.run_timeout_seconds):
                await self._storage.delete_object_if_exists(
                    bucket=snapshot.bucket,
                    key=snapshot.object_key,
                )
        except TimeoutError:
            return await self._commit_failure(
                claimed,
                JobExecutionResult(
                    outcome=JobOutcomeKind.RETRYABLE_FAILURE,
                    error_code="JOB_RUN_TIMEOUT",
                    error_summary=f"对象删除超过运行预算 {budget.run_timeout_seconds} 秒",
                ),
            )
        except ClientError as exc:
            return await self._commit_failure(claimed, self._classify_client_error(exc))
        except BotoCoreError as exc:
            return await self._commit_failure(
                claimed, self._classify_botocore_error(exc)
            )
        except Exception as exc:
            logger.exception("对象清理任务发生未预期异常: job_id=%s", claimed.id)
            return await self._commit_failure(
                claimed,
                JobExecutionResult(
                    outcome=JobOutcomeKind.RETRYABLE_FAILURE,
                    error_code=type(exc).__name__,
                    error_summary=str(exc),
                ),
            )

        # 删源已成功：在同一事务提交清理完成并按需登记 purge_variant_cache
        enqueue_cdn_purge = (
            self._cdn_purge_enabled
            and snapshot.visibility == FileVariantVisibility.PUBLIC
        )
        try:
            async with self._session_factory() as session, session.begin():
                await FileJobRepository(session).complete_cleanup_variant_success(
                    job_id=claimed.id,
                    attempt_count=claimed.attempt_count,
                    asset_id=snapshot.asset_id,
                    variant_id=snapshot.variant_id,
                    enqueue_cdn_purge=enqueue_cdn_purge,
                    now=utc_now(),
                )
        except Exception:
            logger.exception("提交对象清理成功状态失败: job_id=%s", claimed.id)
            return False
        return True

    def _classify_client_error(self, exc: ClientError) -> JobExecutionResult:
        err_code = str((exc.response.get("Error") or {}).get("Code") or "STORAGE_ERROR")
        if is_retryable_storage_error(exc):
            return JobExecutionResult(
                outcome=JobOutcomeKind.RETRYABLE_FAILURE,
                error_code=err_code,
                error_summary="对象存储暂态故障",
            )
        return JobExecutionResult(
            outcome=JobOutcomeKind.PERMANENT_FAILURE,
            error_code=err_code,
            error_summary="对象存储返回不可重试错误",
        )

    def _classify_botocore_error(self, exc: BotoCoreError) -> JobExecutionResult:
        outcome = (
            JobOutcomeKind.RETRYABLE_FAILURE
            if is_retryable_storage_error(exc)
            else JobOutcomeKind.PERMANENT_FAILURE
        )
        return JobExecutionResult(
            outcome=outcome,
            error_code=type(exc).__name__,
            error_summary=str(exc),
        )

    async def _commit_job_succeeded(self, claimed: ClaimedFileJob) -> bool:
        try:
            async with self._session_factory() as session, session.begin():
                await FileJobRepository(session).complete_job_succeeded(
                    job_id=claimed.id,
                    attempt_count=claimed.attempt_count,
                )
        except Exception:
            logger.exception("提交任务成功状态失败: job_id=%s", claimed.id)
            return False
        return True

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
