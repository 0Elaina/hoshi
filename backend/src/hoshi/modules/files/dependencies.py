from typing import Annotated, cast

from fastapi import Depends, Request

from hoshi.api.dependencies import (
    FileStorageDependency,
    RedisDependency,
    SessionDependency,
)
from hoshi.modules.files.rate_limit import UploadRateLimiter
from hoshi.modules.files.schemas import JobWakeupPublisher
from hoshi.modules.files.upload_service import FileUploadService


def get_file_upload_service(
    request: Request,
    session: SessionDependency,
    storage: FileStorageDependency,
    redis: RedisDependency,
) -> FileUploadService:
    """组装文件上传登记与确认用例依赖"""
    wakeup_publisher = cast(
        JobWakeupPublisher | None,
        getattr(request.app.state, "file_job_wakeup_publisher", None),
    )
    return FileUploadService(
        session=session,
        storage=storage,
        rate_limiter=UploadRateLimiter(redis),
        wakeup_publisher=wakeup_publisher,
    )


type FileUploadServiceDependency = Annotated[
    FileUploadService, Depends(get_file_upload_service)
]
