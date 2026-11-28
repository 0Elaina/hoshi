import asyncio
import logging
from contextlib import suppress
from uuid import uuid4

from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hoshi.modules.files.constants import FileUploadConfig
from hoshi.modules.files.enums import (
    FileAssetStatus,
    FileVariantStatus,
    FileVariantVisibility,
    ImagePreset,
    lookup_variant_preset,
)
from hoshi.modules.files.jobs.common import (
    classify_botocore_error,
    classify_client_error,
    commit_job_failure,
    commit_job_succeeded,
)
from hoshi.modules.files.jobs.media import render_image_variant
from hoshi.modules.files.jobs.policy import (
    JobExecutionResult,
    JobOutcomeKind,
    resolve_job_budget,
)
from hoshi.modules.files.object_keys import build_variant_key
from hoshi.modules.files.repositories.jobs import ClaimedFileJob
from hoshi.modules.files.repositories.variants import FileVariantRepository
from hoshi.modules.files.storage.worker import ObjectReadTooLarge, WorkerObjectStorage

logger = logging.getLogger(__name__)

# 私有与公开衍生物写入 S3 时附带的 Cache-Control 策略
PRIVATE_VARIANT_CACHE_CONTROL = "private, max-age=300"
PUBLIC_VARIANT_CACHE_CONTROL = "public, max-age=300, s-maxage=86400"


class GenerateVariantHandler:
    """处理 generate_variant：从私有原件渲染衍生物，公开写前复核状态并在提交时先锁规格"""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        storage: WorkerObjectStorage,
    ) -> None:
        self._session_factory = session_factory
        self._storage = storage

    async def handle(self, claimed: ClaimedFileJob) -> bool:
        if claimed.variant_id is None:
            return await commit_job_failure(
                self._session_factory,
                claimed,
                JobExecutionResult(
                    outcome=JobOutcomeKind.PERMANENT_FAILURE,
                    error_code="MISSING_VARIANT_ID",
                    error_summary="规格生成任务缺少 variant_id",
                ),
            )

        try:
            async with self._session_factory() as session, session.begin():
                snapshot = await FileVariantRepository(
                    session
                ).get_variant_generation_snapshot(claimed.variant_id)
        except Exception:
            logger.exception("读取规格生成快照失败: job_id=%s", claimed.id)
            return False

        if snapshot is None:
            return await commit_job_failure(
                self._session_factory,
                claimed,
                JobExecutionResult(
                    outcome=JobOutcomeKind.PERMANENT_FAILURE,
                    error_code="FILE_VARIANT_NOT_FOUND",
                    error_summary="目标规格记录不存在",
                ),
            )

        # 规格已就绪或已撤回时无需再生成，直接按成功结束任务
        if snapshot.variant_status != FileVariantStatus.UNAVAILABLE:
            return await commit_job_succeeded(self._session_factory, claimed)

        if (
            snapshot.asset_status != FileAssetStatus.READY
            or not snapshot.original_bucket
            or not snapshot.original_key
        ):
            return await commit_job_failure(
                self._session_factory,
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
            return await commit_job_failure(
                self._session_factory,
                claimed,
                JobExecutionResult(
                    outcome=JobOutcomeKind.PERMANENT_FAILURE,
                    error_code="UNSUPPORTED_VARIANT_PRESET",
                    error_summary=f"未支持的图片规格: {snapshot.preset_name}:v{snapshot.preset_revision}",
                ),
            )

        budget = resolve_job_budget(claimed.job_type, snapshot.media_kind)
        is_public = snapshot.visibility == FileVariantVisibility.PUBLIC
        target_bucket = (
            self._storage.public_bucket if is_public else self._storage.private_bucket
        )
        cache_control = (
            PUBLIC_VARIANT_CACHE_CONTROL if is_public else PRIVATE_VARIANT_CACHE_CONTROL
        )
        target_key = build_variant_key(snapshot.asset_id, preset, uuid4())

        rendered_content_type: str | None = None
        rendered_size_bytes: int | None = None
        rendered_width: int | None = None
        rendered_height: int | None = None
        skipped_before_write = False

        try:
            async with asyncio.timeout(budget.run_timeout_seconds):
                read_result = await self._storage.get_object_bytes(
                    bucket=snapshot.original_bucket,
                    key=snapshot.original_key,
                    max_bytes=FileUploadConfig.IMAGE_MAX_SIZE_BYTES,
                )
                if isinstance(read_result, ObjectReadTooLarge):
                    result = JobExecutionResult(
                        outcome=JobOutcomeKind.PERMANENT_FAILURE,
                        error_code="ORIGINAL_TOO_LARGE",
                        error_summary=(
                            f"原件体积超出允许上限 {read_result.max_bytes} 字节"
                        ),
                    )
                else:
                    rendered = await asyncio.to_thread(
                        render_image_variant, read_result, preset=preset
                    )
                    if isinstance(rendered, JobExecutionResult):
                        result = rendered
                    else:
                        # 写入公开桶前二次复核规格未被撤回，防止已撤回产物进入匿名可读公开桶
                        if is_public:
                            async with (
                                self._session_factory() as session,
                                session.begin(),
                            ):
                                still_valid = await FileVariantRepository(
                                    session
                                ).is_variant_still_unavailable(snapshot.variant_id)
                            if not still_valid:
                                skipped_before_write = True

                        if not skipped_before_write:
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
        except ClientError as exc:
            result = classify_client_error(exc)
        except BotoCoreError as exc:
            result = classify_botocore_error(exc)
        except Exception as exc:
            logger.exception("规格生成发生未预期异常: job_id=%s", claimed.id)
            result = JobExecutionResult(
                outcome=JobOutcomeKind.RETRYABLE_FAILURE,
                error_code=type(exc).__name__,
                error_summary=str(exc),
            )

        if result.outcome != JobOutcomeKind.SUCCEEDED:
            return await commit_job_failure(self._session_factory, claimed, result)

        if skipped_before_write:
            return await commit_job_succeeded(self._session_factory, claimed)

        assert rendered_content_type is not None
        assert rendered_size_bytes is not None

        try:
            async with self._session_factory() as session, session.begin():
                registered = await FileVariantRepository(
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
