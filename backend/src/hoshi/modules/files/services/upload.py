import ipaddress
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from hoshi.modules.files.constants import (
    MEDIA_UPLOAD_RULES,
    FileApiCode,
    FileJobTiming,
    FileUploadConfig,
)
from hoshi.modules.files.enums import (
    FileAssetStatus,
    FileJobType,
    MediaFormat,
    MediaKind,
)
from hoshi.modules.files.object_keys import build_upload_key
from hoshi.modules.files.repositories.assets import FileAssetRepository
from hoshi.modules.files.schemas import (
    JobWakeupPublisher,
    UploadConfirmation,
    UploadGrant,
)
from hoshi.modules.files.services.rate_limit import UploadRateLimiter
from hoshi.modules.files.storage import PRESIGN_EXPIRES_SECONDS, FileObjectStorage
from hoshi.shared.http.api_code import CommonApiCode
from hoshi.shared.http.exception import BusinessException
from hoshi.shared.utils.time_utils import utc_now


def try_normalize_mime_type(raw_content_type: str | None) -> str | None:
    """将 MIME 字符串剥离参数并转为小写，空值或含换行时返回 None"""
    if not isinstance(raw_content_type, str):
        return None
    if "\r" in raw_content_type or "\n" in raw_content_type:
        return None
    # 剥离参数段并统一小写，便于跨浏览器与 S3 响应做一致性比对
    media_type = raw_content_type.split(";", 1)[0].strip().lower()
    if not media_type or len(media_type) > FileUploadConfig.MAX_MIME_LENGTH:
        return None
    return media_type


def normalize_mime_type(raw_content_type: str) -> str:
    """规范化请求传入的 MIME 字符串，空值或非法控制字符抛出参数错误"""
    normalized = try_normalize_mime_type(raw_content_type)
    if normalized is None:
        raise BusinessException(CommonApiCode.INVALID_ARGUMENT, "文件 MIME 类型无效")
    return normalized


def normalize_client_ip(raw_client_ip: str) -> str:
    """校验并压缩来源 IP 文本表示，确保限流键规范一致"""
    if not isinstance(raw_client_ip, str) or not (stripped := raw_client_ip.strip()):
        raise BusinessException(CommonApiCode.INVALID_ARGUMENT, "客户端 IP 无效")
    try:
        return ipaddress.ip_address(stripped).compressed
    except ValueError:
        raise BusinessException(
            CommonApiCode.INVALID_ARGUMENT, "客户端 IP 无效"
        ) from None


def _validate_positive_int(value: int, *, message: str) -> int:
    # Python 中 bool 是 int 子类，需显式排除
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BusinessException(CommonApiCode.INVALID_ARGUMENT, message)
    return value


def _validate_uuid4(value: UUID, *, message: str) -> UUID:
    if isinstance(value, UUID) and value.version == 4:
        return value
    raise BusinessException(CommonApiCode.INVALID_ARGUMENT, message)


class FileUploadService:
    """文件直传登记与完成确认用例"""

    def __init__(
        self,
        *,
        session: AsyncSession,
        storage: FileObjectStorage,
        rate_limiter: UploadRateLimiter,
        repository: FileAssetRepository | None = None,
        wakeup_publisher: JobWakeupPublisher | None = None,
    ) -> None:
        self._session = session
        self._storage = storage
        self._rate_limiter = rate_limiter
        self._repository = repository or FileAssetRepository(session)
        self._wakeup_publisher = wakeup_publisher

    async def create_upload(
        self,
        owner_account_id: int,
        client_ip: str,
        media_kind: MediaKind,
        content_type: str,
        size_bytes: int,
    ) -> UploadGrant:
        """校验媒体规则与限流，签发私有桶 PUT 预签名并登记待确认资产"""
        _validate_positive_int(owner_account_id, message="账号 ID 无效")
        if not isinstance(media_kind, MediaKind):
            raise BusinessException(CommonApiCode.INVALID_ARGUMENT, "媒体类型参数无效")
        _validate_positive_int(size_bytes, message="文件大小必须是正整数")
        normalized_content_type = normalize_mime_type(content_type)
        normalized_client_ip = normalize_client_ip(client_ip)

        # 通过统一媒体格式枚举与只读规则检查类型支持和字节上限
        media_format = MediaFormat.from_mime_type(normalized_content_type)
        rule = MEDIA_UPLOAD_RULES.get(media_kind)
        if (
            rule is None
            or media_format is None
            or media_format not in rule.allowed_formats
        ):
            raise BusinessException(FileApiCode.FILE_UPLOAD_UNSUPPORTED_MEDIA)
        if size_bytes > rule.max_size_bytes:
            raise BusinessException(FileApiCode.FILE_UPLOAD_TOO_LARGE)

        await self._rate_limiter.check_upload(
            owner_account_id=owner_account_id,
            client_ip=normalized_client_ip,
        )

        # 先本地生成预签名，再开启短事务登记待确认资产，减少事务持锁时间
        asset_id = uuid4()
        upload_key = build_upload_key(asset_id)
        issued_at = utc_now()
        presigned = await self._storage.presign_put(
            upload_key, media_format.mime_type, size_bytes
        )
        confirm_expires_at = issued_at + timedelta(
            seconds=FileUploadConfig.CONFIRM_TTL_SECONDS
        )

        async with self._session.begin():
            await self._repository.create_pending_asset(
                asset_id=asset_id,
                owner_account_id=owner_account_id,
                media_kind=media_kind,
                declared_content_type=media_format.mime_type,
                declared_size_bytes=size_bytes,
                confirm_expires_at=confirm_expires_at,
                now=issued_at,
            )

        return UploadGrant(
            asset_id=asset_id,
            upload_url=presigned.url,
            upload_headers=presigned.headers,
            upload_expires_in_seconds=PRESIGN_EXPIRES_SECONDS,
            confirm_expires_at=confirm_expires_at,
        )

    async def confirm_upload(
        self, owner_account_id: int, asset_id: UUID
    ) -> UploadConfirmation:
        """核对暂存对象元信息并原子落库待校验状态与校验任务"""
        _validate_positive_int(owner_account_id, message="账号 ID 无效")
        _validate_uuid4(asset_id, message="资产 ID 无效")

        # 读事务只取标量快照并尽早提交退出，避免在 S3 HEAD 期间占用数据库连接
        async with self._session.begin():
            snapshot = await self._repository.get_asset_confirm_snapshot(
                asset_id=asset_id,
                owner_account_id=owner_account_id,
            )

        if snapshot is None:
            raise BusinessException(FileApiCode.FILE_ASSET_NOT_FOUND)
        # 已确认资产直接按历史确认时间幂等返回当前状态
        if snapshot.confirmed_at is not None:
            return UploadConfirmation(
                asset_id=snapshot.id,
                status=snapshot.status,
                confirmed_at=snapshot.confirmed_at,
            )
        if snapshot.status != FileAssetStatus.PENDING_UPLOAD:
            raise BusinessException(FileApiCode.FILE_UPLOAD_METADATA_MISMATCH)
        if utc_now() >= snapshot.confirm_expires_at:
            raise BusinessException(FileApiCode.FILE_UPLOAD_EXPIRED)

        # 在无活跃数据库事务的状态下查询暂存对象元信息
        metadata = await self._storage.head(build_upload_key(asset_id))
        if metadata is None:
            raise BusinessException(FileApiCode.FILE_UPLOAD_NOT_RECEIVED)

        rejected = False
        created_job_id: int | None = None
        confirmation: UploadConfirmation | None = None

        # 写事务加行锁复核状态与元信息；若拒绝须让事务正常提交后再抛出冲突异常
        async with self._session.begin():
            asset = await self._repository.get_asset_for_update(
                asset_id=asset_id,
                owner_account_id=owner_account_id,
            )
            if asset is None:
                raise BusinessException(FileApiCode.FILE_ASSET_NOT_FOUND)
            if asset.confirmed_at is not None:
                confirmation = UploadConfirmation(
                    asset_id=asset.id,
                    status=FileAssetStatus(asset.status),
                    confirmed_at=asset.confirmed_at,
                )
            elif asset.status != FileAssetStatus.PENDING_UPLOAD.value:
                raise BusinessException(FileApiCode.FILE_UPLOAD_METADATA_MISMATCH)
            else:
                now = utc_now()
                if now >= asset.confirm_expires_at:
                    raise BusinessException(FileApiCode.FILE_UPLOAD_EXPIRED)

                actual_content_type = try_normalize_mime_type(metadata.content_type)
                if (
                    metadata.size_bytes != asset.declared_size_bytes
                    or actual_content_type != asset.declared_content_type
                ):
                    asset.status = FileAssetStatus.UPLOAD_REJECTED.value
                    asset.updated_at = now
                    rejected = True
                elif metadata.etag is None or not metadata.etag.strip():
                    # 元信息匹配但 ETag 缺失时不改状态，保留后续重试确认机会
                    raise BusinessException(CommonApiCode.STORAGE_BAD_GATEWAY)
                else:
                    # 原样保存 ETag，并在同一事务登记校验任务以保证受理原子性
                    asset.upload_etag = metadata.etag
                    asset.confirmed_at = now
                    asset.status = FileAssetStatus.PENDING_VALIDATION.value
                    asset.updated_at = now
                    created_job_id = await self._repository.create_validate_upload_job(
                        asset_id=asset.id,
                        available_at=now,
                        next_wakeup_at=now
                        + timedelta(
                            seconds=FileJobTiming.MQ_INITIAL_WAKEUP_DELAY_SECONDS
                        ),
                        now=now,
                    )
                    confirmation = UploadConfirmation(
                        asset_id=asset.id,
                        status=FileAssetStatus.PENDING_VALIDATION,
                        confirmed_at=now,
                    )

        if rejected:
            raise BusinessException(FileApiCode.FILE_UPLOAD_METADATA_MISMATCH)

        # 事务提交后再尝试快速唤醒，避免消费者读到未提交记录
        if created_job_id is not None and self._wakeup_publisher is not None:
            self._wakeup_publisher.schedule_wakeup(
                created_job_id, FileJobType.VALIDATE_UPLOAD
            )

        assert confirmation is not None
        return confirmation
