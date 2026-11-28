import logging

from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hoshi.modules.files.jobs.policy import (
    JobExecutionResult,
    JobOutcomeKind,
    compute_retry_delay_seconds,
    format_last_error,
)
from hoshi.modules.files.repositories.jobs import ClaimedFileJob, FileJobRepository
from hoshi.modules.files.storage.worker import is_retryable_storage_error
from hoshi.shared.utils.time_utils import utc_now

logger = logging.getLogger(__name__)


def classify_client_error(exc: ClientError) -> JobExecutionResult:
    """将 S3 ClientError 归类为可重试暂态故障或永久失败"""
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


def classify_botocore_error(exc: BotoCoreError) -> JobExecutionResult:
    """将 BotoCoreError 归类为可重试连接/超时故障或永久失败"""
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


async def commit_job_succeeded(
    session_factory: async_sessionmaker[AsyncSession],
    claimed: ClaimedFileJob,
) -> bool:
    """提交通用任务成功状态；返回 True 表示数据库已落定可 ACK"""
    try:
        async with session_factory() as session, session.begin():
            await FileJobRepository(session).complete_job_succeeded(
                job_id=claimed.id,
                attempt_count=claimed.attempt_count,
            )
    except Exception:
        logger.exception("提交任务成功状态失败: job_id=%s", claimed.id)
        return False
    return True


async def commit_job_failure(
    session_factory: async_sessionmaker[AsyncSession],
    claimed: ClaimedFileJob,
    result: JobExecutionResult,
) -> bool:
    """按结构化结果提交退避重排或终态失败；返回 True 表示数据库已落定可 ACK"""
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
        async with session_factory() as session, session.begin():
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
