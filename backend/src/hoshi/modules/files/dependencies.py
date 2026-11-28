from typing import Annotated, cast

from fastapi import Depends, Request

from hoshi.api.dependencies import (
    FileStorageDependency,
    RedisDependency,
    SessionDependency,
    SettingsDependency,
)
from hoshi.modules.files.schemas import JobWakeupPublisher
from hoshi.modules.files.services.rate_limit import UploadRateLimiter
from hoshi.modules.files.services.upload import FileUploadService
from hoshi.modules.files.services.variants import FileVariantService


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


def get_file_variant_service(
    request: Request,
    session: SessionDependency,
    storage: FileStorageDependency,
    settings: SettingsDependency,
) -> FileVariantService:
    """组装文件规格申请、批量访问与撤回用例依赖"""
    wakeup_publisher = cast(
        JobWakeupPublisher | None,
        getattr(request.app.state, "file_job_wakeup_publisher", None),
    )
    return FileVariantService(
        session=session,
        storage=storage,
        public_media_base_url=settings.public_media_base_url,
        wakeup_publisher=wakeup_publisher,
    )


type FileVariantServiceDependency = Annotated[
    FileVariantService, Depends(get_file_variant_service)
]
