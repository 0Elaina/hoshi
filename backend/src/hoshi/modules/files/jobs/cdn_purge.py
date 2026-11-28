import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hoshi.modules.files.jobs.policy import (
    DEFAULT_CDN_HTTP_TIMEOUT_SECONDS,
    format_last_error,
)
from hoshi.modules.files.repositories.maintenance import (
    ClaimedCdnPurgeJob,
    FileMaintenanceRepository,
)
from hoshi.modules.files.storage.cdn import (
    CdnPurgeAdapter,
    CdnPurgeOutcome,
    CdnPurgeResult,
    build_public_media_url,
)
from hoshi.shared.utils.time_utils import utc_now

logger = logging.getLogger(__name__)

# 默认单轮 CDN 批量 URL 上限（供应商限额更低时按配额覆盖）
DEFAULT_CDN_PURGE_BATCH_LIMIT = 30


class CdnPurgeBatchProcessor:
    """分钟维护循环调用的 CDN 批量领取与清理处理器（每轮至多发一次 HTTP 请求）"""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        adapter: CdnPurgeAdapter,
        public_media_base_url: str,
        batch_limit: int = DEFAULT_CDN_PURGE_BATCH_LIMIT,
        http_timeout_seconds: float = DEFAULT_CDN_HTTP_TIMEOUT_SECONDS,
    ) -> None:
        if batch_limit <= 0:
            raise ValueError("batch_limit 必须是正整数")
        self._session_factory = session_factory
        self._adapter = adapter
        self._public_media_base_url = public_media_base_url
        self._batch_limit = batch_limit
        self._http_timeout_seconds = http_timeout_seconds

    async def run_one_batch(self) -> None:
        """领取一批到期 purge_variant_cache 任务，去重 URL 发一次请求后按尝试号批量回写"""
        async with self._session_factory() as session, session.begin():
            claimed = await FileMaintenanceRepository(session).claim_cdn_purge_batch(
                limit=self._batch_limit
            )

        if not claimed:
            return

        # 区分缺失对象键的异常记录与有效任务，并对公开 URL 去重
        missing_location_jobs: list[ClaimedCdnPurgeJob] = []
        valid_jobs: list[ClaimedCdnPurgeJob] = []
        unique_urls_map: dict[str, None] = {}

        for job in claimed:
            if not job.object_key:
                missing_location_jobs.append(job)
                continue
            valid_jobs.append(job)
            url = build_public_media_url(self._public_media_base_url, job.object_key)
            unique_urls_map[url] = None

        if missing_location_jobs:
            async with self._session_factory() as session, session.begin():
                await FileMaintenanceRepository(session).complete_cdn_purge_batch(
                    jobs=missing_location_jobs,
                    outcome=CdnPurgeOutcome.PERMANENT_FAILURE.value,
                    last_error=format_last_error(
                        "MISSING_OBJECT_KEY", "公开规格缺少对象键，无法执行 CDN 清理"
                    ),
                    retry_after_seconds=None,
                    now=utc_now(),
                )

        if not valid_jobs:
            return

        urls = list(unique_urls_map.keys())
        # 在数据库事务外向 CDN 供应商发出单次批量清理 HTTP 请求
        try:
            async with asyncio.timeout(self._http_timeout_seconds):
                result = await self._adapter.purge_urls(urls)
        except TimeoutError:
            result = CdnPurgeResult(
                outcome=CdnPurgeOutcome.RETRYABLE_FAILURE,
                error_code="CDN_PURGE_TIMEOUT",
            )
        except Exception as exc:
            logger.warning(
                "CDN 批量清理请求异常: batch_size=%s urls=%s",
                len(valid_jobs),
                len(urls),
                exc_info=True,
            )
            result = CdnPurgeResult(
                outcome=CdnPurgeOutcome.RETRYABLE_FAILURE,
                error_code=type(exc).__name__,
            )

        last_error = (
            None
            if result.outcome == CdnPurgeOutcome.SUCCEEDED
            else format_last_error(result.error_code or "CDN_PURGE_FAILED")
        )
        # 按领取时的 (job_id, attempt_count) 条件批量回写结果
        async with self._session_factory() as session, session.begin():
            await FileMaintenanceRepository(session).complete_cdn_purge_batch(
                jobs=valid_jobs,
                outcome=result.outcome.value,
                last_error=last_error,
                retry_after_seconds=result.retry_after_seconds,
                now=utc_now(),
            )
        logger.info(
            "CDN 批量清理完成: jobs=%s unique_urls=%s outcome=%s error_code=%s",
            len(valid_jobs),
            len(urls),
            result.outcome.value,
            result.error_code,
        )
