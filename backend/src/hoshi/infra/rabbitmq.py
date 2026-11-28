import asyncio
import json
import logging
from contextlib import suppress
from types import TracebackType
from typing import Self

import aio_pika
from aio_pika import DeliveryMode, Message
from aio_pika.abc import (
    AbstractRobustChannel,
    AbstractRobustConnection,
    AbstractRobustQueue,
)

from hoshi.core.config import RabbitMQSettings
from hoshi.modules.files.enums import FileJobType

logger = logging.getLogger(__name__)

# 队列积压上限、快速路径在途上限与发布/重连超时默认值
DEFAULT_QUEUE_MAX_LENGTH = 10_000
DEFAULT_MAX_INFLIGHT_PUBLISHES = 8
DEFAULT_PUBLISH_TIMEOUT_SECONDS = 2.0
DEFAULT_CONNECT_RETRY_INTERVAL_SECONDS = 5.0


def media_queue_name(app_env: str) -> str:
    """按运行环境隔离的媒体任务队列名"""
    return f"hoshi.{app_env}.files.media"


def cleanup_queue_name(app_env: str) -> str:
    """按运行环境隔离的对象清理队列名"""
    return f"hoshi.{app_env}.files.cleanup"


def queue_name_for_job_type(app_env: str, job_type: FileJobType) -> str:
    """将可走 MQ 唤醒的任务类型映射到目标队列，CDN 清理任务禁止走 MQ"""
    # 上传校验与规格生成共走媒体队列
    if job_type in (FileJobType.VALIDATE_UPLOAD, FileJobType.GENERATE_VARIANT):
        return media_queue_name(app_env)
    # 撤回删源独立走对象清理队列，避免被媒体处理阻塞
    if job_type == FileJobType.CLEANUP_VARIANT:
        return cleanup_queue_name(app_env)
    raise ValueError(f"任务类型 {job_type.value} 不走 RabbitMQ 唤醒队列")


async def declare_file_queues(
    channel: AbstractRobustChannel,
    app_env: str,
    *,
    max_length: int = DEFAULT_QUEUE_MAX_LENGTH,
) -> tuple[AbstractRobustQueue, AbstractRobustQueue]:
    """声明按环境隔离的媒体与对象清理 durable 队列"""
    # 队列满时拒绝发布而非丢弃旧消息，由数据库补发循环兜底
    arguments: dict[str, int | str] = {
        "x-max-length": max_length,
        "x-overflow": "reject-publish",
    }
    media_queue = await channel.declare_queue(
        media_queue_name(app_env),
        durable=True,
        arguments=arguments,
    )
    cleanup_queue = await channel.declare_queue(
        cleanup_queue_name(app_env),
        durable=True,
        arguments=arguments,
    )
    return media_queue, cleanup_queue


def encode_job_message(job_id: int) -> Message:
    """将 job_id 编码为持久化 JSON 消息体"""
    # 消息体仅携带最小 job_id，真实状态以 PostgreSQL 为准
    body = json.dumps({"job_id": job_id}, separators=(",", ":")).encode("utf-8")
    return Message(
        body=body,
        content_type="application/json",
        delivery_mode=DeliveryMode.PERSISTENT,
    )


def decode_job_id(body: bytes) -> int | None:
    """解析消息体中的正整数 job_id，排除 bool 及畸形载荷"""
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    job_id = payload.get("job_id")
    # Python 中 bool 是 int 子类，须显式排除
    if isinstance(job_id, bool) or not isinstance(job_id, int) or job_id <= 0:
        return None
    return job_id


async def connect_rabbitmq(
    config: RabbitMQSettings, *, timeout: float = DEFAULT_PUBLISH_TIMEOUT_SECONDS
) -> AbstractRobustConnection:
    """建立 aio-pika robust 连接，启用断线自动重连"""
    # fail_fast=False 允许网络抖动时持续重连，不直接放弃连接对象
    return await aio_pika.connect_robust(
        host=config.host,
        port=config.port,
        login=config.user,
        password=config.password.get_secret_value(),
        virtualhost=config.vhost,
        timeout=timeout,
        fail_fast=False,
    )


class RabbitMQFileJobPublisher:
    """进程内共享的文件任务 RabbitMQ 发布器（非阻塞启动、有界并发快速唤醒）"""

    def __init__(
        self,
        config: RabbitMQSettings,
        *,
        app_env: str,
        max_inflight: int = DEFAULT_MAX_INFLIGHT_PUBLISHES,
        publish_timeout: float = DEFAULT_PUBLISH_TIMEOUT_SECONDS,
        queue_max_length: int = DEFAULT_QUEUE_MAX_LENGTH,
        connect_retry_interval: float = DEFAULT_CONNECT_RETRY_INTERVAL_SECONDS,
    ) -> None:
        self._config = config
        self._app_env = app_env
        self._max_inflight = max_inflight
        self._publish_timeout = publish_timeout
        self._queue_max_length = queue_max_length
        self._connect_retry_interval = connect_retry_interval

        # 进程级共享连接与发布通道
        self._connection: AbstractRobustConnection | None = None
        self._channel: AbstractRobustChannel | None = None
        self._ready = False
        self._closed = False
        self._connect_task: asyncio.Task[None] | None = None
        # 持有强引用防止后台发布任务被 GC，同时作为在途并发准入计数
        self._inflight_tasks: set[asyncio.Task[None]] = set()

    async def __aenter__(self) -> Self:
        self.start()
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        await self.close()

    def start(self) -> None:
        """非阻塞启动后台建连，Broker 暂不可用时不阻断 Web 启动"""
        if self._closed or self._connect_task is not None:
            return
        self._connect_task = asyncio.create_task(self._connect_loop())

    def is_ready(self) -> bool:
        """仅在建连、开通道与声明队列全部完成且未关闭时视为可发布"""
        return (
            not self._closed
            and self._ready
            and self._connection is not None
            and not self._connection.is_closed
            and self._channel is not None
            and not self._channel.is_closed
        )

    async def _connect_loop(self) -> None:
        """后台循环建连并声明队列，成功后交由 aio-pika robust 连接维持后续重连"""
        while not self._closed:
            connection: AbstractRobustConnection | None = None
            try:
                connection = await connect_rabbitmq(
                    self._config, timeout=self._publish_timeout
                )
                # 开启发布确认与不可路由回退抛错，避免消息静默丢失
                channel = await connection.channel(
                    publisher_confirms=True,
                    on_return_raises=True,
                )
                # 队列在连接就绪前声明完成，robust 通道重连时会自动重放声明
                await declare_file_queues(
                    channel,
                    self._app_env,
                    max_length=self._queue_max_length,
                )
                # 建连期间若进程已进入关闭流程，立即释放新连接
                if self._closed:
                    await connection.close()
                    return
                self._connection = connection
                self._channel = channel
                self._ready = True
                logger.info(
                    "RabbitMQ 文件任务发布器已就绪: host=%s port=%s env=%s",
                    self._config.host,
                    self._config.port,
                    self._app_env,
                )
                return
            except asyncio.CancelledError:
                # 取消时清理可能已建立的半成品连接
                if connection is not None and not connection.is_closed:
                    with suppress(Exception):
                        await connection.close()
                raise
            except Exception:
                # 启动期 Broker 不可达仅记告警并间隔重试，不阻塞业务请求
                logger.warning(
                    "RabbitMQ 初始连接未就绪，将在 %.1fs 后重试（期间由数据库补发接管）",
                    self._connect_retry_interval,
                    exc_info=True,
                )
                if connection is not None and not connection.is_closed:
                    with suppress(Exception):
                        await connection.close()
                await asyncio.sleep(self._connect_retry_interval)

    async def publish_now(
        self,
        job_id: int,
        job_type: FileJobType,
        *,
        timeout: float | None = None,
    ) -> bool:
        """同步等待一次带确认的持久化发布，失败记 warning 并返回 False"""
        if not self.is_ready() or self._channel is None:
            return False

        queue_name = queue_name_for_job_type(self._app_env, job_type)
        effective_timeout = self._publish_timeout if timeout is None else timeout
        try:
            # 外层总超时覆盖发布与确认全过程，避免网络挂起拖垮调用方
            async with asyncio.timeout(effective_timeout):
                await self._channel.default_exchange.publish(
                    encode_job_message(job_id),
                    routing_key=queue_name,
                    mandatory=True,
                    timeout=effective_timeout,
                )
            return True
        except asyncio.CancelledError:
            raise
        except Exception:
            # 快速路径与补发路径均不向上抛异常，由数据库状态兜底
            logger.warning(
                "RabbitMQ 文件任务唤醒发布失败: job_id=%s job_type=%s queue=%s",
                job_id,
                job_type.value,
                queue_name,
                exc_info=True,
            )
            return False

    def schedule_wakeup(self, job_id: int, job_type: FileJobType) -> None:
        """快速路径后台投递：先检查就绪态与在途容量，超额或未就绪直接由数据库补发接管"""
        # CDN 清理只走分钟维护循环批领，不进入 MQ
        if job_type == FileJobType.PURGE_VARIANT_CACHE:
            return
        # 连接未就绪直接跳过，不触发数据库往返
        if not self.is_ready():
            return
        # 先判容量再创建任务，避免 Broker 抖动时无界堆积后台协程
        if len(self._inflight_tasks) >= self._max_inflight:
            return

        task = asyncio.create_task(self._publish_background(job_id, job_type))
        self._inflight_tasks.add(task)
        # 完成后自动移出强引用集合，释放并发名额
        task.add_done_callback(self._inflight_tasks.discard)

    async def _publish_background(self, job_id: int, job_type: FileJobType) -> None:
        await self.publish_now(job_id, job_type)

    async def close(self) -> None:
        """取消后台建连与在途发布，按通道到连接顺序释放资源"""
        self._closed = True
        self._ready = False

        # 先停后台建连循环，避免关闭过程中重新拉起连接
        if self._connect_task is not None:
            self._connect_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._connect_task
            self._connect_task = None

        # 取消全部在途快速发布并等待收敛
        inflight = list(self._inflight_tasks)
        for task in inflight:
            task.cancel()
        if inflight:
            await asyncio.gather(*inflight, return_exceptions=True)
        self._inflight_tasks.clear()

        # 先关通道再关连接，确保服务端干净回收
        if self._channel is not None and not self._channel.is_closed:
            with suppress(Exception):
                await self._channel.close()
        self._channel = None

        if self._connection is not None and not self._connection.is_closed:
            with suppress(Exception):
                await self._connection.close()
        self._connection = None
