from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from hoshi.modules.files.cdn import build_public_media_url
from hoshi.modules.files.constants import FileApiCode
from hoshi.modules.files.enums import (
    FileAssetStatus,
    FileJobType,
    FileVariantStatus,
    FileVariantVisibility,
    lookup_variant_preset,
)
from hoshi.modules.files.schemas import (
    JobWakeupPublisher,
    VariantAccessView,
    VariantRecord,
)
from hoshi.modules.files.storage import FileObjectStorage
from hoshi.modules.files.variant_repository import FileVariantRepository
from hoshi.shared.http.api_code import CommonApiCode
from hoshi.shared.http.exception import BusinessException
from hoshi.shared.utils.time_utils import utc_now


def _validate_uuid4(value: UUID, *, message: str) -> UUID:
    if isinstance(value, UUID) and value.version == 4:
        return value
    raise BusinessException(CommonApiCode.INVALID_ARGUMENT, message)


class FileVariantService:
    """文件规格申请、批量访问地址生成与显式撤回用例"""

    def __init__(
        self,
        *,
        session: AsyncSession,
        storage: FileObjectStorage,
        public_media_base_url: str | None = None,
        repository: FileVariantRepository | None = None,
        wakeup_publisher: JobWakeupPublisher | None = None,
    ) -> None:
        self._session = session
        self._storage = storage
        self._public_media_base_url = public_media_base_url
        self._repository = repository or FileVariantRepository(session)
        self._wakeup_publisher = wakeup_publisher

    async def request_variant(
        self,
        *,
        asset_id: UUID,
        preset_name: str,
        preset_revision: int,
        visibility: FileVariantVisibility = FileVariantVisibility.PRIVATE,
    ) -> VariantRecord:
        """并发安全申请规格：部分索引去重插入 → 冲突后 FOR UPDATE 锁定 → 补建活跃生成任务"""
        _validate_uuid4(asset_id, message="资产 ID 无效")
        if not isinstance(visibility, FileVariantVisibility):
            raise BusinessException(CommonApiCode.INVALID_ARGUMENT, "可见性参数无效")

        created_job_id: int | None = None
        variant: VariantRecord | None = None

        async with self._session.begin():
            asset = await self._repository.get_asset_readiness(asset_id)
            if asset is None:
                raise BusinessException(FileApiCode.FILE_ASSET_NOT_FOUND)

            preset = lookup_variant_preset(
                asset.media_kind, preset_name, preset_revision
            )
            if preset is None:
                raise BusinessException(
                    CommonApiCode.INVALID_ARGUMENT, "未登记的文件规格名称或版本"
                )

            if asset.status != FileAssetStatus.READY:
                raise BusinessException(FileApiCode.FILE_ASSET_NOT_READY)

            now = utc_now()
            # 1. 先尝试直接插入 unavailable 规格（由部分唯一索引解决首次并发创建）
            variant = await self._repository.try_insert_unavailable_variant(
                asset_id=asset_id,
                preset_name=preset.preset_name,
                preset_revision=preset.revision,
                visibility=visibility,
                now=now,
            )

            # 2. 冲突时独立执行 SELECT FOR UPDATE 锁定同元组未撤回记录
            if variant is None:
                variant = await self._repository.lock_active_variant(
                    asset_id=asset_id,
                    preset_name=preset.preset_name,
                    preset_revision=preset.revision,
                    visibility=visibility,
                )
                # 冲突后加锁前该规格已被撤回，返回 409 由业务重新授权后发起新申请
                if variant is None:
                    raise BusinessException(FileApiCode.FILE_VARIANT_WITHDRAWN)

            # 3. 已 ready 直接复用返回；unavailable 时按活跃任务部分索引补建 generate_variant
            if variant.status == FileVariantStatus.UNAVAILABLE:
                created_job_id = (
                    await self._repository.try_enqueue_generate_variant_job(
                        asset_id=asset_id,
                        variant_id=variant.id,
                        now=now,
                    )
                )

        # 仅当本事务 RETURNING 得到新任务 ID 时，在提交后触发快速唤醒
        if created_job_id is not None and self._wakeup_publisher is not None:
            self._wakeup_publisher.schedule_wakeup(
                created_job_id, FileJobType.GENERATE_VARIANT
            )

        assert variant is not None
        return variant

    async def get_variants_status(
        self, variant_ids: Sequence[UUID]
    ) -> dict[UUID, VariantRecord]:
        """纯状态轮询查询，不签发访问 URL"""
        unique_ids = list(
            dict.fromkeys(
                _validate_uuid4(vid, message="规格 ID 无效") for vid in variant_ids
            )
        )
        if not unique_ids:
            return {}

        async with self._session.begin():
            rows = await self._repository.get_variants_by_ids(unique_ids)

        return {row.record.id: row.record for row in rows}

    async def get_variants_with_urls(
        self, variant_ids: Sequence[UUID]
    ) -> dict[UUID, VariantAccessView]:
        """单次集合查询批量读取规格，事务外本地签发私有 URL 或拼接公开 URL"""
        unique_ids = list(
            dict.fromkeys(
                _validate_uuid4(vid, message="规格 ID 无效") for vid in variant_ids
            )
        )
        if not unique_ids:
            return {}

        async with self._session.begin():
            rows = await self._repository.get_variants_by_ids(unique_ids)

        views: dict[UUID, VariantAccessView] = {}
        for row in rows:
            record = row.record
            url: str | None = None
            # 仅 ready 状态返回访问地址；unavailable 与 withdrawn 一律不返回地址
            if record.status == FileVariantStatus.READY and row.object_key:
                if record.visibility == FileVariantVisibility.PRIVATE:
                    # 复用固定应用凭据做纯本地 SigV4 签名，零 S3 网络请求
                    url = await self._storage.presign_get(row.object_key)
                elif self._public_media_base_url is not None:
                    url = build_public_media_url(
                        self._public_media_base_url, row.object_key
                    )
            views[record.id] = VariantAccessView(variant=record, url=url)

        return views

    async def withdraw_variants(self, variant_ids: Sequence[UUID]) -> list[UUID]:
        """显式撤回规格：原子置 withdrawn 并为已有物理对象批量登记删源任务"""
        unique_ids = list(
            dict.fromkeys(
                _validate_uuid4(vid, message="规格 ID 无效") for vid in variant_ids
            )
        )
        if not unique_ids:
            return []

        async with self._session.begin():
            (
                withdrawn_ids,
                created_job_ids,
            ) = await self._repository.withdraw_variants_and_enqueue_cleanup(
                variant_ids=unique_ids,
                now=utc_now(),
            )

        # 事务提交后立刻唤醒对象清理队列；业务层随之停止返回已撤回地址
        if self._wakeup_publisher is not None:
            for job_id in created_job_ids:
                self._wakeup_publisher.schedule_wakeup(
                    job_id, FileJobType.CLEANUP_VARIANT
                )

        return withdrawn_ids
