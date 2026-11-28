# 文件资产、规格与后台任务表

## file_assets 表

存储用户与管理员直传登记的文件资产元数据、确认状态、暂存对象 ETag 及校验通过后的私有原件物理位置。

**字段**

| 字段名 | 类型 | 约束(PK/FK/UNIQUE/NOT NULL/DEFAULT) | 说明（枚举须写全映射） |
| --- | --- | --- | --- |
| `id` | `UUID` | `PK, NOT NULL` | 资产主键，由应用生成 UUID v4 |
| `owner_account_id` | `BIGINT` | `FK(user_accounts.id), NOT NULL` | 上传归属账号 ID，外键约束 `ON DELETE RESTRICT` |
| `media_kind` | `VARCHAR(16)` | `NOT NULL` | 媒体大类：`image`、`audio`、`video`（数据库不硬编码枚举 CHECK） |
| `status` | `VARCHAR(24)` | `NOT NULL, DEFAULT 'pending_upload'` | 资产状态：`pending_upload`、`upload_rejected`、`pending_validation`、`ready`、`validation_rejected`、`validation_failed` |
| `declared_content_type` | `VARCHAR(127)` | `NOT NULL` | 登记时规范化后的小写 MIME 类型 |
| `declared_size_bytes` | `BIGINT` | `NOT NULL, CHECK (> 0)` | 登记时声明的文件字节数 |
| `confirm_expires_at` | `TIMESTAMPTZ` | `NOT NULL` | 完成确认窗口截止时间（签发时间加 15 分钟） |
| `confirmed_at` | `TIMESTAMPTZ` | `NULL` | 首次确认受理时间（UTC），兼作重复确认幂等依据 |
| `upload_etag` | `TEXT` | `NULL` | 确认时原样保存的暂存对象 ETag，供 Worker 执行 `If-Match` 条件读取 |
| `original_bucket` | `VARCHAR(63)` | `NULL` | 校验通过后私有原件所在桶名 |
| `original_key` | `TEXT` | `NULL` | 校验通过后私有原件对象键 |
| `original_content_type` | `VARCHAR(127)` | `NULL` | 校验通过后私有原件 MIME 类型 |
| `original_size_bytes` | `BIGINT` | `NULL, CHECK (IS NULL OR > 0)` | 校验通过后私有原件字节数 |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL, DEFAULT CURRENT_TIMESTAMP` | 创建时间（UTC） |
| `updated_at` | `TIMESTAMPTZ` | `NOT NULL, DEFAULT CURRENT_TIMESTAMP` | 更新时间（UTC），状态变更显式刷新 |

**索引**

| 索引名 | 类型 | 字段 | 理由（必须说明具体查询场景） |
| --- | --- | --- | --- |
| `pk_file_assets` | 主键 | `id` | 确认上传、校验读取与规格生成时按资产 ID 精确定位 |
| `ix_file_assets_owner_account_id` | 普通 | `owner_account_id` | 按上传账号查询其文件资产并支撑 `user_accounts.id` 外键反查 |

**关系**

| 关系 | 目标表 | 外键字段 | 说明 |
| --- | --- | --- | --- |
| N:1 | `user_accounts` | `owner_account_id` | 资产所属上传账号，`ON DELETE RESTRICT` |

**建表 SQL**

```sql
CREATE TABLE file_assets (
    id UUID NOT NULL,
    owner_account_id BIGINT NOT NULL,
    media_kind VARCHAR(16) NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'pending_upload',
    declared_content_type VARCHAR(127) NOT NULL,
    declared_size_bytes BIGINT NOT NULL,
    confirm_expires_at TIMESTAMPTZ NOT NULL,
    confirmed_at TIMESTAMPTZ,
    upload_etag TEXT,
    original_bucket VARCHAR(63),
    original_key TEXT,
    original_content_type VARCHAR(127),
    original_size_bytes BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_file_assets PRIMARY KEY (id),
    CONSTRAINT ck_file_assets_declared_size_bytes_positive CHECK (declared_size_bytes > 0),
    CONSTRAINT ck_file_assets_original_size_bytes_positive CHECK (original_size_bytes IS NULL OR original_size_bytes > 0),
    CONSTRAINT fk_file_assets_owner_account_id_user_accounts FOREIGN KEY (owner_account_id)
        REFERENCES user_accounts (id) ON DELETE RESTRICT
);

CREATE INDEX ix_file_assets_owner_account_id ON file_assets (owner_account_id);
```

## file_variants 表

存储已就绪文件资产在私有桶或公开桶中的衍生规格记录、状态、物理对象位置及媒体尺寸信息。

**字段**

| 字段名 | 类型 | 约束(PK/FK/UNIQUE/NOT NULL/DEFAULT) | 说明（枚举须写全映射） |
| --- | --- | --- | --- |
| `id` | `UUID` | `PK, NOT NULL` | 规格主键，由应用生成 UUID v4 |
| `asset_id` | `UUID` | `FK(file_assets.id), NOT NULL` | 所属文件资产 ID，外键约束 `ON DELETE RESTRICT` |
| `preset_name` | `VARCHAR(64)` | `NOT NULL` | 已登记的规格名称（如 `full`） |
| `preset_revision` | `INTEGER` | `NOT NULL, CHECK (> 0)` | 规格版本号（正整数） |
| `visibility` | `VARCHAR(8)` | `NOT NULL, DEFAULT 'private'` | 可见性：`private`（私有桶）、`public`（公开桶） |
| `status` | `VARCHAR(16)` | `NOT NULL, DEFAULT 'unavailable'` | 规格状态：`unavailable`、`ready`、`withdrawn`；`ready` 约束桶/键/类型/大小必填，撤回保留已有位置供后台清理 |
| `bucket` | `VARCHAR(63)` | `NULL` | 衍生对象所在桶名 |
| `object_key` | `TEXT` | `NULL` | 衍生对象键 |
| `content_type` | `VARCHAR(127)` | `NULL` | 衍生对象 MIME 类型 |
| `size_bytes` | `BIGINT` | `NULL, CHECK (IS NULL OR > 0)` | 衍生对象字节数 |
| `width` | `INTEGER` | `NULL, CHECK (IS NULL OR > 0)` | 图片或视频宽度（像素） |
| `height` | `INTEGER` | `NULL, CHECK (IS NULL OR > 0)` | 图片或视频高度（像素） |
| `duration_ms` | `BIGINT` | `NULL, CHECK (IS NULL OR >= 0)` | 音视频时长（毫秒） |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL, DEFAULT CURRENT_TIMESTAMP` | 创建时间（UTC） |
| `updated_at` | `TIMESTAMPTZ` | `NOT NULL, DEFAULT CURRENT_TIMESTAMP` | 更新时间（UTC） |

**索引**

| 索引名 | 类型 | 字段 | 理由（必须说明具体查询场景） |
| --- | --- | --- | --- |
| `pk_file_variants` | 主键 | `id` | 批量查询规格访问地址、撤回及后台任务读写规格时按 ID 定位 |
| `ix_file_variants_asset_id` | 普通 | `asset_id` | 按资产 ID 查询含撤回记录在内的全量规格并支撑 `file_assets.id` 外键反查 |
| `uq_file_variants_active_spec` | 部分唯一 | `(asset_id, preset_name, preset_revision, visibility) WHERE status <> 'withdrawn'` | 保障同资产、同规格版本与同可见性下仅存在一条未撤回记录，配合 `ON CONFLICT DO NOTHING` 解决首次并发申请 |

**关系**

| 关系 | 目标表 | 外键字段 | 说明 |
| --- | --- | --- | --- |
| N:1 | `file_assets` | `asset_id` | 规格所属文件资产，`ON DELETE RESTRICT` |

**建表 SQL**

```sql
CREATE TABLE file_variants (
    id UUID NOT NULL,
    asset_id UUID NOT NULL,
    preset_name VARCHAR(64) NOT NULL,
    preset_revision INTEGER NOT NULL,
    visibility VARCHAR(8) NOT NULL DEFAULT 'private',
    status VARCHAR(16) NOT NULL DEFAULT 'unavailable',
    bucket VARCHAR(63),
    object_key TEXT,
    content_type VARCHAR(127),
    size_bytes BIGINT,
    width INTEGER,
    height INTEGER,
    duration_ms BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_file_variants PRIMARY KEY (id),
    CONSTRAINT ck_file_variants_preset_revision_positive CHECK (preset_revision > 0),
    CONSTRAINT ck_file_variants_size_bytes_positive CHECK (size_bytes IS NULL OR size_bytes > 0),
    CONSTRAINT ck_file_variants_width_positive CHECK (width IS NULL OR width > 0),
    CONSTRAINT ck_file_variants_height_positive CHECK (height IS NULL OR height > 0),
    CONSTRAINT ck_file_variants_duration_ms_non_negative CHECK (duration_ms IS NULL OR duration_ms >= 0),
    CONSTRAINT ck_file_variants_ready_requires_object_location CHECK (
        status <> 'ready'
        OR (bucket IS NOT NULL AND object_key IS NOT NULL AND content_type IS NOT NULL AND size_bytes IS NOT NULL)
    ),
    CONSTRAINT fk_file_variants_asset_id_file_assets FOREIGN KEY (asset_id)
        REFERENCES file_assets (id) ON DELETE RESTRICT
);

CREATE INDEX ix_file_variants_asset_id ON file_variants (asset_id);
CREATE UNIQUE INDEX uq_file_variants_active_spec
    ON file_variants (asset_id, preset_name, preset_revision, visibility)
    WHERE status <> 'withdrawn';
```

## file_jobs 表

存储文件上传校验、衍生规格生成、撤回删源与 CDN 缓存清理的后台任务状态、调度时间与尝试记录。

**字段**

| 字段名 | 类型 | 约束(PK/FK/UNIQUE/NOT NULL/DEFAULT) | 说明（枚举须写全映射） |
| --- | --- | --- | --- |
| `id` | `BIGINT` | `PK, IDENTITY, NOT NULL` | 任务自增主键，兼作 MQ 唤醒消息载荷 `job_id` |
| `asset_id` | `UUID` | `FK(file_assets.id), NOT NULL` | 关联文件资产 ID，`ON DELETE RESTRICT` |
| `variant_id` | `UUID` | `FK(file_variants.id), NULL` | 关联规格 ID，`ON DELETE RESTRICT`；约束仅 `validate_upload` 为空，其余任务必填 |
| `job_type` | `VARCHAR(32)` | `NOT NULL` | 任务类型：`validate_upload`、`generate_variant`、`cleanup_variant`、`purge_variant_cache` |
| `status` | `VARCHAR(16)` | `NOT NULL, DEFAULT 'pending'` | 任务状态：`pending`、`running`、`succeeded`、`failed` |
| `available_at` | `TIMESTAMPTZ` | `NOT NULL` | 任务最早可被领取执行时间（UTC） |
| `next_wakeup_at` | `TIMESTAMPTZ` | `NOT NULL, CHECK (>= available_at)` | 数据库补发循环下次唤醒时间（MQ 任务初值为 `available_at + 60s`，CDN 任务等于 `available_at`） |
| `attempt_count` | `INTEGER` | `NOT NULL, DEFAULT 0, CHECK (>= 0)` | 累计领取尝试次数，最大 3 次 |
| `last_error` | `TEXT` | `NULL, CHECK (IS NULL OR char_length <= 512)` | 最近一次失败错误码与清理后的摘要，合计最多 512 字符 |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL, DEFAULT CURRENT_TIMESTAMP` | 创建时间（UTC） |
| `updated_at` | `TIMESTAMPTZ` | `NOT NULL, DEFAULT CURRENT_TIMESTAMP` | 状态变更时间（UTC）；MQ 补发推迟 `next_wakeup_at` 时保持原值 |

**索引**

| 索引名 | 类型 | 字段 | 理由（必须说明具体查询场景） |
| --- | --- | --- | --- |
| `pk_file_jobs` | 主键 | `id` | 消费者收到唤醒 `job_id` 时单条 `UPDATE RETURNING` 原子领取与结果回写 |
| `ix_file_jobs_asset_id` | 普通 | `asset_id` | 按资产 ID 检索关联任务并支撑 `file_assets.id` 外键反查 |
| `uq_file_jobs_validate_upload_asset` | 部分唯一 | `(asset_id) WHERE job_type = 'validate_upload'` | 防止同一文件资产重复登记上传校验任务 |
| `uq_file_jobs_active_variant_job` | 部分唯一 | `(variant_id, job_type) WHERE variant_id IS NOT NULL AND status IN ('pending', 'running')` | 约束同规格同类型至多存在一条活跃任务，同时允许历史 `failed` 任务保留诊断信息 |
| `ix_file_jobs_running_or_succeeded` | 部分普通 | `(status, updated_at, id) WHERE status IN ('running', 'succeeded')` | 支撑分钟维护循环的超时 `running` 回收与超 30 天 `succeeded` 历史清理 |
| `ix_file_jobs_pending_mq_wakeup` | 部分普通 | `(next_wakeup_at, id) WHERE status = 'pending' AND job_type <> 'purge_variant_cache'` | 支撑 MQ 补发按 `(next_wakeup_at, id)` 跳过已锁行批领，与 CDN 积压互斥隔离 |
| `ix_file_jobs_pending_cdn_purge` | 部分普通 | `(available_at, id) WHERE status = 'pending' AND job_type = 'purge_variant_cache'` | 支撑分钟维护循环按 `(available_at, id)` 直接批领到期 CDN 缓存清理任务 |

**关系**

| 关系 | 目标表 | 外键字段 | 说明 |
| --- | --- | --- | --- |
| N:1 | `file_assets` | `asset_id` | 任务所属文件资产，`ON DELETE RESTRICT` |
| N:1 | `file_variants` | `variant_id` | 非上传校验任务关联的目标规格，`ON DELETE RESTRICT` |

**建表 SQL**

```sql
CREATE TABLE file_jobs (
    id BIGINT GENERATED BY DEFAULT AS IDENTITY,
    asset_id UUID NOT NULL,
    variant_id UUID,
    job_type VARCHAR(32) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    available_at TIMESTAMPTZ NOT NULL,
    next_wakeup_at TIMESTAMPTZ NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_file_jobs PRIMARY KEY (id),
    CONSTRAINT ck_file_jobs_variant_id_by_job_type CHECK (
        (job_type = 'validate_upload' AND variant_id IS NULL)
        OR (job_type <> 'validate_upload' AND variant_id IS NOT NULL)
    ),
    CONSTRAINT ck_file_jobs_next_wakeup_at_gte_available_at CHECK (next_wakeup_at >= available_at),
    CONSTRAINT ck_file_jobs_attempt_count_non_negative CHECK (attempt_count >= 0),
    CONSTRAINT ck_file_jobs_last_error_max_length CHECK (last_error IS NULL OR char_length(last_error) <= 512),
    CONSTRAINT fk_file_jobs_asset_id_file_assets FOREIGN KEY (asset_id)
        REFERENCES file_assets (id) ON DELETE RESTRICT,
    CONSTRAINT fk_file_jobs_variant_id_file_variants FOREIGN KEY (variant_id)
        REFERENCES file_variants (id) ON DELETE RESTRICT
);

CREATE INDEX ix_file_jobs_asset_id ON file_jobs (asset_id);
CREATE UNIQUE INDEX uq_file_jobs_validate_upload_asset
    ON file_jobs (asset_id)
    WHERE job_type = 'validate_upload';
CREATE UNIQUE INDEX uq_file_jobs_active_variant_job
    ON file_jobs (variant_id, job_type)
    WHERE variant_id IS NOT NULL AND status IN ('pending', 'running');
CREATE INDEX ix_file_jobs_running_or_succeeded
    ON file_jobs (status, updated_at, id)
    WHERE status IN ('running', 'succeeded');
CREATE INDEX ix_file_jobs_pending_mq_wakeup
    ON file_jobs (next_wakeup_at, id)
    WHERE status = 'pending' AND job_type <> 'purge_variant_cache';
CREATE INDEX ix_file_jobs_pending_cdn_purge
    ON file_jobs (available_at, id)
    WHERE status = 'pending' AND job_type = 'purge_variant_cache';
```
