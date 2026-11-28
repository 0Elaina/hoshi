import logging
from collections.abc import Awaitable, Callable, Sequence

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hoshi.modules.files.enums import FileJobType
from hoshi.modules.files.jobs.cleanup_variant import CleanupVariantHandler
from hoshi.modules.files.jobs.common import commit_job_failure
from hoshi.modules.files.jobs.generate_variant import GenerateVariantHandler
from hoshi.modules.files.jobs.policy import JobExecutionResult, JobOutcomeKind
from hoshi.modules.files.jobs.validate_upload import ValidateUploadHandler
from hoshi.modules.files.repositories.jobs import ClaimedFileJob, FileJobRepository
from hoshi.modules.files.storage.worker import WorkerObjectStorage

logger = logging.getLogger(__name__)

type JobHandler = Callable[[ClaimedFileJob], Awaitable[bool]]


class FileJobRunner:
    """文件任务轻量分发器：原子领取后按任务类型派发到对应处理器"""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        storage: WorkerObjectStorage,
        cdn_purge_enabled: bool = False,
        extra_handlers: dict[FileJobType, JobHandler] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._handlers: dict[FileJobType, JobHandler] = {
            FileJobType.VALIDATE_UPLOAD: ValidateUploadHandler(
                session_factory=session_factory,
                storage=storage,
            ).handle,
            FileJobType.GENERATE_VARIANT: GenerateVariantHandler(
                session_factory=session_factory,
                storage=storage,
            ).handle,
            FileJobType.CLEANUP_VARIANT: CleanupVariantHandler(
                session_factory=session_factory,
                storage=storage,
                cdn_purge_enabled=cdn_purge_enabled,
            ).handle,
        }
        if extra_handlers:
            self._handlers.update(extra_handlers)

    async def process_job_id(
        self, *, job_id: int, allowed_job_types: Sequence[FileJobType]
    ) -> bool:
        """领取单个唤醒 job_id 并派发执行；返回 True 表示可安全 ACK"""
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

        handler = self._handlers.get(claimed.job_type)
        if handler is not None:
            return await handler(claimed)

        return await commit_job_failure(
            self._session_factory,
            claimed,
            JobExecutionResult(
                outcome=JobOutcomeKind.PERMANENT_FAILURE,
                error_code="UNSUPPORTED_JOB_TYPE",
                error_summary=f"未注册任务处理器: {claimed.job_type.value}",
            ),
        )
