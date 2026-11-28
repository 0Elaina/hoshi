from enum import StrEnum


class FileAssetStatus(StrEnum):
    PENDING_UPLOAD = "pending_upload"
    UPLOAD_REJECTED = "upload_rejected"
    PENDING_VALIDATION = "pending_validation"
    READY = "ready"
    VALIDATION_REJECTED = "validation_rejected"
    VALIDATION_FAILED = "validation_failed"


class FileJobType(StrEnum):
    VALIDATE_UPLOAD = "validate_upload"
    GENERATE_VARIANT = "generate_variant"
    CLEANUP_VARIANT = "cleanup_variant"
    PURGE_VARIANT_CACHE = "purge_variant_cache"


class FileJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class FileVariantVisibility(StrEnum):
    PRIVATE = "private"
    PUBLIC = "public"


class FileVariantStatus(StrEnum):
    UNAVAILABLE = "unavailable"
    READY = "ready"
    WITHDRAWN = "withdrawn"
