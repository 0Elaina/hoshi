from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from hoshi.db.base import Base
from hoshi.modules.files.enums import (
    FileAssetStatus,
    FileJobStatus,
    FileVariantStatus,
    FileVariantVisibility,
)
from hoshi.shared.utils.time_utils import utc_now


class FileAsset(Base):
    """文件上传与私有原件元数据记录"""

    __tablename__ = "file_assets"
    __table_args__ = (
        CheckConstraint(
            "declared_size_bytes > 0",
            name="declared_size_bytes_positive",
        ),
        CheckConstraint(
            "original_size_bytes IS NULL OR original_size_bytes > 0",
            name="original_size_bytes_positive",
        ),
        Index("ix_file_assets_owner_account_id", "owner_account_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    owner_account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    media_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=FileAssetStatus.PENDING_UPLOAD.value,
        server_default=text("'pending_upload'"),
    )
    declared_content_type: Mapped[str] = mapped_column(String(127), nullable=False)
    declared_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    confirm_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    upload_etag: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_bucket: Mapped[str | None] = mapped_column(String(63), nullable=True)
    original_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_content_type: Mapped[str | None] = mapped_column(
        String(127), nullable=True
    )
    original_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.current_timestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.current_timestamp(),
    )


class FileVariant(Base):
    """文件资产的私有/公开衍生规格记录"""

    __tablename__ = "file_variants"
    __table_args__ = (
        CheckConstraint(
            "preset_revision > 0",
            name="preset_revision_positive",
        ),
        CheckConstraint(
            "size_bytes IS NULL OR size_bytes > 0",
            name="size_bytes_positive",
        ),
        CheckConstraint(
            "width IS NULL OR width > 0",
            name="width_positive",
        ),
        CheckConstraint(
            "height IS NULL OR height > 0",
            name="height_positive",
        ),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="duration_ms_non_negative",
        ),
        # ready 状态必须具备完整对象桶、键、MIME 与字节数，撤回保留位置供后台清理
        CheckConstraint(
            "status <> 'ready' OR ("
            "bucket IS NOT NULL AND object_key IS NOT NULL "
            "AND content_type IS NOT NULL AND size_bytes IS NOT NULL"
            ")",
            name="ready_requires_object_location",
        ),
        # 完整索引覆盖外键反查与含撤回记录的查询
        Index("ix_file_variants_asset_id", "asset_id"),
        # 部分唯一索引保障同资产同规格同可见性下仅有一条未撤回记录，解决首次并发创建
        Index(
            "uq_file_variants_active_spec",
            "asset_id",
            "preset_name",
            "preset_revision",
            "visibility",
            unique=True,
            postgresql_where=text("status <> 'withdrawn'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    asset_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("file_assets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    preset_name: Mapped[str] = mapped_column(String(64), nullable=False)
    preset_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    visibility: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        default=FileVariantVisibility.PRIVATE.value,
        server_default=text("'private'"),
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=FileVariantStatus.UNAVAILABLE.value,
        server_default=text("'unavailable'"),
    )
    bucket: Mapped[str | None] = mapped_column(String(63), nullable=True)
    object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(127), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.current_timestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.current_timestamp(),
    )


class FileJob(Base):
    """文件校验、规格生成、删源与 CDN 清理任务队列记录"""

    __tablename__ = "file_jobs"
    __table_args__ = (
        CheckConstraint(
            "(job_type = 'validate_upload' AND variant_id IS NULL) "
            "OR (job_type <> 'validate_upload' AND variant_id IS NOT NULL)",
            name="variant_id_by_job_type",
        ),
        CheckConstraint(
            "next_wakeup_at >= available_at",
            name="next_wakeup_at_gte_available_at",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="attempt_count_non_negative",
        ),
        CheckConstraint(
            "last_error IS NULL OR char_length(last_error) <= 512",
            name="last_error_max_length",
        ),
        Index("ix_file_jobs_asset_id", "asset_id"),
        Index(
            "uq_file_jobs_validate_upload_asset",
            "asset_id",
            unique=True,
            postgresql_where=text("job_type = 'validate_upload'"),
        ),
        Index(
            "uq_file_jobs_active_variant_job",
            "variant_id",
            "job_type",
            unique=True,
            postgresql_where=text(
                "variant_id IS NOT NULL AND status IN ('pending', 'running')"
            ),
        ),
        Index(
            "ix_file_jobs_running_or_succeeded",
            "status",
            "updated_at",
            "id",
            postgresql_where=text("status IN ('running', 'succeeded')"),
        ),
        Index(
            "ix_file_jobs_pending_mq_wakeup",
            "next_wakeup_at",
            "id",
            postgresql_where=text(
                "status = 'pending' AND job_type <> 'purge_variant_cache'"
            ),
        ),
        Index(
            "ix_file_jobs_pending_cdn_purge",
            "available_at",
            "id",
            postgresql_where=text(
                "status = 'pending' AND job_type = 'purge_variant_cache'"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    asset_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("file_assets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # 非 validate_upload 任务关联的目标规格，采用 ON DELETE RESTRICT 保护引用完整性
    variant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("file_variants.id", ondelete="RESTRICT"),
        nullable=True,
    )
    job_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=FileJobStatus.PENDING.value,
        server_default=text("'pending'"),
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    next_wakeup_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.current_timestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.current_timestamp(),
    )
