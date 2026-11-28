import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from uuid import uuid4

from redis import RedisError
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hoshi.infra.rabbitmq import RabbitMQFileJobPublisher
from hoshi.modules.files.constants import FileRedisKey
from hoshi.modules.files.repositories.maintenance import (
    FileMaintenanceRepository,
    WakeupJobItem,
)
from hoshi.shared.utils.time_utils import utc_now

logger = logging.getLogger(__name__)

# 分钟维护循环周期、Redis 租约 TTL 与单轮总预算
SWEEPER_INTERVAL_SECONDS = 60.0
SWEEPER_LOCK_TTL_SECONDS = 55
SWEEPER_ROUND_BUDGET_SECONDS = 30.0

# 每轮超时回收、历史清理与 MQ 补发批次限制
SWEEPER_RECLAIM_LIMIT = 100
SWEEPER_HISTORY_RETENTION_DAYS = 30
SWEEPER_HISTORY_DELETE_LIMIT = 500
SWEEPER_WAKEUP_BATCH_LIMIT = 100
SWEEPER_WAKEUP_DELAY_SECONDS = 180
SWEEPER_WAKEUP_PUBLISH_CONCURRENCY = 16
SWEEPER_WAKEUP_PUBLISH_TIMEOUT_SECONDS = 2.0

type CdnBatchHandler = Callable[[], Awaitable[None]]


class FileMaintenanceSweeper:
    """1 分钟周期维护循环：超时回收、30 天成功历史清理、MQ 补发与 CDN 批领"""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        redis: Redis,
        app_env: str,
        publisher: RabbitMQFileJobPublisher | None = None,
        cdn_batch_handler: CdnBatchHandler | None = None,
        interval_seconds: float = SWEEPER_INTERVAL_SECONDS,
        round_budget_seconds: float = SWEEPER_ROUND_BUDGET_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._redis = redis
        self._lock_key = f"{FileRedisKey.PREFIX}sweeper:{app_env}:lock"
        self._publisher = publisher
        self._cdn_batch_handler = cdn_batch_handler
        self._interval_seconds = interval_seconds
        self._round_budget_seconds = round_budget_seconds

    async def _try_acquire_lease(self) -> bool:
        """沿用 SET ... NX EX 55 抢占本分钟维护租约，租约自然到期不主动删除"""
        try:
            acquired = await self._redis.set(
                self._lock_key,
                uuid4().hex,
                nx=True,
                ex=SWEEPER_LOCK_TTL_SECONDS,
            )
            return bool(acquired)
        except (RedisError, TimeoutError, OSError):
            logger.warning(
                "获取文件维护租约失败，跳过本轮: key=%s", self._lock_key, exc_info=True
            )
            return False

    async def run_once(self) -> None:
        """执行单轮维护：先回收超时与清理历史，再分别运行 MQ 补发与 CDN 批领"""
        if not await self._try_acquire_lease():
            return

        deadline = time.monotonic() + self._round_budget_seconds

        # 1. 回收最多 100 条超时 running 任务
        try:
            async with self._session_factory() as session, session.begin():
                summary = await FileMaintenanceRepository(
                    session
                ).reclaim_timed_out_jobs(
                    now=utc_now(),
                    limit=SWEEPER_RECLAIM_LIMIT,
                )
            if summary.requeued_count or summary.failed_count:
                logger.info(
                    "文件超时任务回收完成: requeued=%s failed=%s",
                    summary.requeued_count,
                    summary.failed_count,
                )
        except Exception:
            logger.exception("文件超时任务回收异常")

        # 2. 清理最多 500 条超 30 天的 succeeded 历史（失败历史保留）
        if time.monotonic() < deadline:
            try:
                async with self._session_factory() as session, session.begin():
                    deleted = await FileMaintenanceRepository(
                        session
                    ).cleanup_succeeded_job_history(
                        retention_days=SWEEPER_HISTORY_RETENTION_DAYS,
                        limit=SWEEPER_HISTORY_DELETE_LIMIT,
                    )
                if deleted:
                    logger.info("已清理超期成功文件任务历史: deleted=%s", deleted)
            except Exception:
                logger.exception("清理成功文件任务历史异常")

        # 3. 独立运行 MQ 补发（独立会话与短事务）
        if self._publisher is not None and time.monotonic() < deadline:
            await self._run_mq_wakeup_batches(deadline)

        # 4. 独立运行 CDN 批领（每轮至多一次批量 HTTP 清理请求）
        if self._cdn_batch_handler is not None and time.monotonic() < deadline:
            try:
                await self._cdn_batch_handler()
            except Exception:
                logger.exception("CDN 批量清理轮次异常")

    async def _run_mq_wakeup_batches(self, deadline: float) -> None:
        """循环按批领取待补发 MQ 任务并并发发布，遇空批、整批失败或预算耗尽立即停止"""
        assert self._publisher is not None
        if not self._publisher.is_ready():
            logger.warning("RabbitMQ 发布器未就绪，跳过本轮数据库补发")
            return

        semaphore = asyncio.Semaphore(SWEEPER_WAKEUP_PUBLISH_CONCURRENCY)

        async def _publish_item(item: WakeupJobItem) -> bool:
            async with semaphore:
                assert self._publisher is not None
                return await self._publisher.publish_now(
                    item.id,
                    item.job_type,
                    timeout=SWEEPER_WAKEUP_PUBLISH_TIMEOUT_SECONDS,
                )

        while time.monotonic() < deadline:
            try:
                async with self._session_factory() as session, session.begin():
                    batch = await FileMaintenanceRepository(
                        session
                    ).claim_mq_wakeup_batch(
                        limit=SWEEPER_WAKEUP_BATCH_LIMIT,
                        wakeup_delay_seconds=SWEEPER_WAKEUP_DELAY_SECONDS,
                    )
            except Exception:
                logger.exception("批量领取待补发 MQ 任务失败")
                return

            if not batch:
                return

            results = await asyncio.gather(*(_publish_item(item) for item in batch))
            succeeded = sum(1 for ok in results if ok)
            failed = len(results) - succeeded
            logger.info(
                "MQ 补发批次完成: total=%s succeeded=%s failed=%s",
                len(batch),
                succeeded,
                failed,
            )
            # 整批全部失败通常意味着 Broker 异常，立即结束本轮避免空转
            if succeeded == 0:
                return

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        """按 1 分钟周期常驻运行直到收到停机信号"""
        while not stop_event.is_set():
            started_at = time.monotonic()
            await self.run_once()
            elapsed = time.monotonic() - started_at
            remaining = max(0.0, self._interval_seconds - elapsed)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=remaining)
            except TimeoutError:
                continue
