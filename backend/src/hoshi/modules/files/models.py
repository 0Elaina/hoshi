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
from hoshi.modules.files.enums import FileAssetStatus, FileJobStatus
from hoshi.shared.utils.time_utils import utc_now


class FileAsset(Base):
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


class FileJob(Base):
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
    variant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
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
