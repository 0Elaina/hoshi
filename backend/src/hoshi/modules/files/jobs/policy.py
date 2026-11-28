from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from hoshi.modules.files.enums import FileJobType, MediaKind

# 单任务最大尝试次数及第 1/2 次可重试失败的退避秒数
MAX_JOB_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS: tuple[int, ...] = (30, 120)
MAX_LAST_ERROR_LENGTH = 512

# 图片任务默认运行预算 120 秒、超时回收阈值 180 秒；CDN HTTP 超时 10 秒
DEFAULT_IMAGE_RUN_TIMEOUT_SECONDS = 120
DEFAULT_IMAGE_RECLAIM_SECONDS = 180
DEFAULT_CLEANUP_RUN_TIMEOUT_SECONDS = 30
DEFAULT_CLEANUP_RECLAIM_SECONDS = 90
DEFAULT_CDN_HTTP_TIMEOUT_SECONDS = 10
DEFAULT_CDN_RECLAIM_SECONDS = 60


class JobOutcomeKind(StrEnum):
    SUCCEEDED = "succeeded"
    RETRYABLE_FAILURE = "retryable_failure"
    PERMANENT_FAILURE = "permanent_failure"
    VALIDATION_REJECTED = "validation_rejected"


@dataclass(frozen=True, slots=True)
class JobBudget:
    run_timeout_seconds: int
    reclaim_after_seconds: int


@dataclass(frozen=True, slots=True)
class JobExecutionResult:
    outcome: JobOutcomeKind
    error_code: str | None = None
    error_summary: str | None = None
    retry_after_seconds: int | None = None


# 领取运行超时与维护循环超时回收共用同一份策略映射
JOB_BUDGET_POLICIES: Mapping[tuple[FileJobType, MediaKind | None], JobBudget] = (
    MappingProxyType(
        {
            (FileJobType.VALIDATE_UPLOAD, MediaKind.IMAGE): JobBudget(
                run_timeout_seconds=DEFAULT_IMAGE_RUN_TIMEOUT_SECONDS,
                reclaim_after_seconds=DEFAULT_IMAGE_RECLAIM_SECONDS,
            ),
            (FileJobType.GENERATE_VARIANT, MediaKind.IMAGE): JobBudget(
                run_timeout_seconds=DEFAULT_IMAGE_RUN_TIMEOUT_SECONDS,
                reclaim_after_seconds=DEFAULT_IMAGE_RECLAIM_SECONDS,
            ),
            (FileJobType.CLEANUP_VARIANT, None): JobBudget(
                run_timeout_seconds=DEFAULT_CLEANUP_RUN_TIMEOUT_SECONDS,
                reclaim_after_seconds=DEFAULT_CLEANUP_RECLAIM_SECONDS,
            ),
            (FileJobType.PURGE_VARIANT_CACHE, None): JobBudget(
                run_timeout_seconds=DEFAULT_CDN_HTTP_TIMEOUT_SECONDS,
                reclaim_after_seconds=DEFAULT_CDN_RECLAIM_SECONDS,
            ),
        }
    )
)

DEFAULT_JOB_BUDGET = JobBudget(
    run_timeout_seconds=DEFAULT_IMAGE_RUN_TIMEOUT_SECONDS,
    reclaim_after_seconds=DEFAULT_IMAGE_RECLAIM_SECONDS,
)


def resolve_job_budget(
    job_type: FileJobType, media_kind: MediaKind | None = None
) -> JobBudget:
    """按任务类型与媒体类型查找运行预算与回收阈值"""
    if media_kind is not None:
        specific = JOB_BUDGET_POLICIES.get((job_type, media_kind))
        if specific is not None:
            return specific
    fallback = JOB_BUDGET_POLICIES.get((job_type, None))
    return fallback if fallback is not None else DEFAULT_JOB_BUDGET


def compute_retry_delay_seconds(
    attempt_count: int, *, retry_after_seconds: int | None = None
) -> int | None:
    """按当前尝试号计算下次重试退避秒数；达到最大尝试次数返回 None"""
    if attempt_count >= MAX_JOB_ATTEMPTS:
        return None
    # attempt_count 从 1 开始，对应 RETRY_BACKOFF_SECONDS 下标 0、1
    index = max(0, min(attempt_count - 1, len(RETRY_BACKOFF_SECONDS) - 1))
    base_delay = RETRY_BACKOFF_SECONDS[index]
    if retry_after_seconds is not None and retry_after_seconds > base_delay:
        return retry_after_seconds
    return base_delay


def format_last_error(error_code: str | None, summary: str | None = None) -> str | None:
    """清理控制字符并拼接错误码与摘要，严格截断至 512 字符以内"""
    clean_code = " ".join((error_code or "").split())
    clean_summary = " ".join((summary or "").split())
    if clean_code and clean_summary:
        combined = f"{clean_code}: {clean_summary}"
    else:
        combined = clean_code or clean_summary
    if not combined:
        return None
    return combined[:MAX_LAST_ERROR_LENGTH]
