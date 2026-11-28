import argparse
import asyncio
import logging
import signal
from collections.abc import Sequence
from contextlib import AsyncExitStack, suppress

from aio_pika.abc import AbstractIncomingMessage
from aiobotocore.session import get_session
from redis.asyncio import Redis

from hoshi.core.config import Settings
from hoshi.core.logging import configure_logging
from hoshi.db.session import create_db_engine, create_session_factory
from hoshi.infra.rabbitmq import (
    RabbitMQFileJobPublisher,
    connect_rabbitmq,
    declare_file_queues,
    decode_job_id,
)
from hoshi.infra.s3 import create_s3_client
from hoshi.modules.files.enums import FileJobType
from hoshi.modules.files.jobs.cdn_purge import CdnPurgeBatchProcessor
from hoshi.modules.files.jobs.runner import FileJobRunner
from hoshi.modules.files.jobs.sweeper import CdnBatchHandler, FileMaintenanceSweeper
from hoshi.modules.files.storage.cdn import CdnPurgeAdapter
from hoshi.modules.files.storage.worker import WorkerObjectStorage

logger = logging.getLogger(__name__)

# Worker 独立调优的 S3 读超时与连接池大小
WORKER_S3_READ_TIMEOUT_SECONDS = 30.0
WORKER_S3_MAX_POOL_CONNECTIONS = 32

# 媒体与对象清理队列各自的预取与并发上限
MEDIA_QUEUE_PREFETCH_COUNT = 4
CLEANUP_QUEUE_PREFETCH_COUNT = 32
CLEANUP_MAX_CONCURRENCY = 16

ALL_WORKER_ROLES = frozenset({"media", "cleanup", "sweeper"})


def _parse_roles(raw_roles: str) -> frozenset[str]:
    """解析命令行 --roles 参数并校验合法性"""
    roles = frozenset(part.strip() for part in raw_roles.split(",") if part.strip())
    if not roles or not roles.issubset(ALL_WORKER_ROLES):
        allowed = ",".join(sorted(ALL_WORKER_ROLES))
        raise ValueError(f"--roles 仅允许以下取值组合: {allowed}")
    return roles


def _make_message_handler(
    *,
    runner: FileJobRunner,
    allowed_job_types: Sequence[FileJobType],
    semaphore: asyncio.Semaphore,
):
    """构造带并发信号量与确定性 ACK/NACK 语义的 AMQP 消费回调"""

    async def _on_message(message: AbstractIncomingMessage) -> None:
        job_id = decode_job_id(message.body)
        # 无法解析的毒丸消息记告警并直接 ACK，避免无限重投阻塞队列
        if job_id is None:
            logger.warning("丢弃格式非法的任务唤醒消息: body=%r", message.body[:200])
            await message.ack()
            return

        async with semaphore:
            should_ack = await runner.process_job_id(
                job_id=job_id,
                allowed_job_types=allowed_job_types,
            )

        if should_ack:
            await message.ack()
        elif not message.redelivered:
            # 首次遇到数据库未落定允许一次快速重投，覆盖短暂抖动
            await message.nack(requeue=True)
        else:
            # 已重投仍失败时停止立即循环重投，交由数据库补发与超时回收接管
            logger.warning(
                "唤醒消息重投后仍未能提交数据库，停止立即重投并交由维护循环兜底: job_id=%s",
                job_id,
            )
            await message.ack()

    return _on_message


async def run_files_worker(
    *,
    roles: frozenset[str],
    cdn_purge_adapter: CdnPurgeAdapter | None = None,
) -> None:
    """装配数据库、Redis、S3 与 RabbitMQ 资源并运行文件后台 Worker"""
    settings = Settings()  # pyright: ignore
    configure_logging(settings)

    s3_settings = settings.s3_config()
    if s3_settings is None:
        raise RuntimeError("启动文件 Worker 前必须启用双桶对象存储配置（HOSHI_S3_*）")

    rabbitmq_settings = settings.rabbitmq_config()
    if ("media" in roles or "cleanup" in roles) and rabbitmq_settings is None:
        raise RuntimeError(
            "启动 media/cleanup 消费者前必须配置 RabbitMQ（HOSHI_RABBITMQ_*）"
        )

    # 启用 CDN 清理的维护进程必须注入具体供应商适配器，否则启动阶段即失败
    if "sweeper" in roles and settings.cdn_purge_enabled and cdn_purge_adapter is None:
        raise RuntimeError(
            "启用 HOSHI_CDN_PURGE_ENABLED 时，sweeper 角色必须注入具体的 CdnPurgeAdapter；"
            "未接入供应商前请保持 HOSHI_CDN_PURGE_ENABLED=false 或仅以 --roles media,cleanup 运行"
        )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)

    engine = create_db_engine(settings.database_url())
    session_factory = create_session_factory(engine)
    background_tasks: list[asyncio.Task[None]] = []

    try:
        async with AsyncExitStack() as stack:
            password = settings.redis_password
            redis = await stack.enter_async_context(
                Redis(
                    host=settings.redis_host,
                    port=settings.redis_port,
                    db=0,
                    password=password.get_secret_value() if password else None,
                    socket_connect_timeout=2.0,
                    socket_timeout=2.0,
                )
            )

            # Worker 按流式 I/O 与实际并发独立设置 S3 读超时和连接池
            s3_client = await stack.enter_async_context(
                create_s3_client(
                    endpoint_url=s3_settings.endpoint_url,
                    region_name=s3_settings.region,
                    access_key=s3_settings.access_key,
                    secret_key=s3_settings.secret_key,
                    read_timeout=WORKER_S3_READ_TIMEOUT_SECONDS,
                    max_pool_connections=WORKER_S3_MAX_POOL_CONNECTIONS,
                    session=get_session(),
                )
            )
            worker_storage = WorkerObjectStorage(
                s3_client,
                private_bucket=s3_settings.private_bucket,
                public_bucket=s3_settings.public_bucket,
            )

            publisher: RabbitMQFileJobPublisher | None = None
            if rabbitmq_settings is not None:
                publisher = await stack.enter_async_context(
                    RabbitMQFileJobPublisher(
                        rabbitmq_settings,
                        app_env=settings.app_env,
                    )
                )

            runner = FileJobRunner(
                session_factory=session_factory,
                storage=worker_storage,
                cdn_purge_enabled=settings.cdn_purge_enabled,
            )

            # 按需启动媒体与对象清理队列消费者
            if (
                "media" in roles or "cleanup" in roles
            ) and rabbitmq_settings is not None:
                consumer_conn = await connect_rabbitmq(rabbitmq_settings)
                stack.push_async_callback(consumer_conn.close)

                if "media" in roles:
                    media_channel = await consumer_conn.channel()
                    await media_channel.set_qos(
                        prefetch_count=MEDIA_QUEUE_PREFETCH_COUNT
                    )
                    media_queue, _ = await declare_file_queues(
                        media_channel, settings.app_env
                    )
                    media_sem = asyncio.Semaphore(MEDIA_QUEUE_PREFETCH_COUNT)
                    await media_queue.consume(
                        _make_message_handler(
                            runner=runner,
                            allowed_job_types=(
                                FileJobType.VALIDATE_UPLOAD,
                                FileJobType.GENERATE_VARIANT,
                            ),
                            semaphore=media_sem,
                        )
                    )

                if "cleanup" in roles:
                    cleanup_channel = await consumer_conn.channel()
                    await cleanup_channel.set_qos(
                        prefetch_count=CLEANUP_QUEUE_PREFETCH_COUNT
                    )
                    _, cleanup_queue = await declare_file_queues(
                        cleanup_channel, settings.app_env
                    )
                    cleanup_sem = asyncio.Semaphore(CLEANUP_MAX_CONCURRENCY)
                    await cleanup_queue.consume(
                        _make_message_handler(
                            runner=runner,
                            allowed_job_types=(FileJobType.CLEANUP_VARIANT,),
                            semaphore=cleanup_sem,
                        )
                    )

            # 按需启动 1 分钟维护循环（超时回收、历史清理、MQ 补发与 CDN 批领）
            if "sweeper" in roles:
                cdn_batch_handler: CdnBatchHandler | None = None
                if settings.cdn_purge_enabled:
                    assert cdn_purge_adapter is not None
                    assert settings.public_media_base_url is not None
                    cdn_processor = CdnPurgeBatchProcessor(
                        session_factory=session_factory,
                        adapter=cdn_purge_adapter,
                        public_media_base_url=settings.public_media_base_url,
                    )
                    cdn_batch_handler = cdn_processor.run_one_batch

                sweeper = FileMaintenanceSweeper(
                    session_factory=session_factory,
                    redis=redis,
                    app_env=settings.app_env,
                    publisher=publisher,
                    cdn_batch_handler=cdn_batch_handler,
                )
                background_tasks.append(
                    asyncio.create_task(sweeper.run_forever(stop_event))
                )

            logger.info(
                "Hoshi 文件 Worker 已启动: env=%s roles=%s",
                settings.app_env,
                ",".join(sorted(roles)),
            )
            await stop_event.wait()
            logger.info("收到停机信号，正在优雅关闭文件 Worker")

            for task in background_tasks:
                task.cancel()
            if background_tasks:
                await asyncio.gather(*background_tasks, return_exceptions=True)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Hoshi 文件后台任务 Worker")
    parser.add_argument(
        "--roles",
        default="media,cleanup,sweeper",
        help="启用的角色列表，逗号分隔（可选: media, cleanup, sweeper）",
    )
    args = parser.parse_args()
    roles = _parse_roles(args.roles)
    asyncio.run(run_files_worker(roles=roles))


if __name__ == "__main__":
    main()
