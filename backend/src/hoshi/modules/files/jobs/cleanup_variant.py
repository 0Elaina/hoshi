import asyncio
import logging

from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hoshi.modules.files.enums import FileVariantStatus, FileVariantVisibility
from hoshi.modules.files.jobs.common import (
    classify_botocore_error,
    classify_client_error,
    commit_job_failure,
    commit_job_succeeded,
)
from hoshi.modules.files.jobs.policy import (
    JobExecutionResult,
    JobOutcomeKind,
    resolve_job_budget,
)
from hoshi.modules.files.repositories.jobs import ClaimedFileJob, FileJobRepository
from hoshi.modules.files.repositories.variants import FileVariantRepository
from hoshi.modules.files.storage.worker import WorkerObjectStorage
from hoshi.shared.utils.time_utils import utc_now

logger = logging.getLogger(__name__)


class CleanupVariantHandler:
    """处理 cleanup_variant：删除已撤回规格的源对象，成功后同事务按需登记 CDN 清理"""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        storage: WorkerObjectStorage,
        cdn_purge_enabled: bool = False,
    ) -> None:
        self._session_factory = session_factory
        self._storage = storage
        self._cdn_purge_enabled = cdn_purge_enabled

    async def handle(self, claimed: ClaimedFileJob) -> bool:
        if claimed.variant_id is None:
            return await commit_job_failure(
                self._session_factory,
                claimed,
                JobExecutionResult(
                    outcome=JobOutcomeKind.PERMANENT_FAILURE,
                    error_code="MISSING_VARIANT_ID",
                    error_summary="对象清理任务缺少 variant_id",
                ),
            )

        try:
            async with self._session_factory() as session, session.begin():
                snapshot = await FileVariantRepository(
                    session
                ).get_variant_cleanup_snapshot(claimed.variant_id)
        except Exception:
            logger.exception("读取待清理规格快照失败: job_id=%s", claimed.id)
            return False

        if snapshot is None:
            return await commit_job_failure(
                self._session_factory,
                claimed,
                JobExecutionResult(
                    outcome=JobOutcomeKind.PERMANENT_FAILURE,
                    error_code="FILE_VARIANT_NOT_FOUND",
                    error_summary="待清理规格不存在",
                ),
            )

        # 防御性检查：严禁删除非 withdrawn 规格的物理对象
        if snapshot.status != FileVariantStatus.WITHDRAWN:
            return await commit_job_failure(
                self._session_factory,
                claimed,
                JobExecutionResult(
                    outcome=JobOutcomeKind.PERMANENT_FAILURE,
                    error_code="VARIANT_NOT_WITHDRAWN",
                    error_summary=f"规格状态为 {snapshot.status.value}，拒绝删除源对象",
                ),
            )

        # 未曾落盘对象的已撤回规格直接成功收口，不登记 CDN 清理
        if not snapshot.bucket or not snapshot.object_key:
            return await commit_job_succeeded(self._session_factory, claimed)

        budget = resolve_job_budget(claimed.job_type)
        try:
            async with asyncio.timeout(budget.run_timeout_seconds):
                await self._storage.delete_object_if_exists(
                    bucket=snapshot.bucket,
                    key=snapshot.object_key,
                )
        except TimeoutError:
            return await commit_job_failure(
                self._session_factory,
                claimed,
                JobExecutionResult(
                    outcome=JobOutcomeKind.RETRYABLE_FAILURE,
                    error_code="JOB_RUN_TIMEOUT",
                    error_summary=f"对象删除超过运行预算 {budget.run_timeout_seconds} 秒",
                ),
            )
        except ClientError as exc:
            return await commit_job_failure(
                self._session_factory, claimed, classify_client_error(exc)
            )
        except BotoCoreError as exc:
            return await commit_job_failure(
                self._session_factory, claimed, classify_botocore_error(exc)
            )
        except Exception as exc:
            logger.exception("对象清理任务发生未预期异常: job_id=%s", claimed.id)
            return await commit_job_failure(
                self._session_factory,
                claimed,
                JobExecutionResult(
                    outcome=JobOutcomeKind.RETRYABLE_FAILURE,
                    error_code=type(exc).__name__,
                    error_summary=str(exc),
                ),
            )

        # 只有删源成功，才在同一事务为启用 CDN 的公开对象登记 purge_variant_cache
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
