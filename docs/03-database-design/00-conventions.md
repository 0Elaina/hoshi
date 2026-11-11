# 数据库通用约定

## 创建与更新时间

需要审计时间戳的表使用 `created_at`、`updated_at`。Go 模型对应字段为 `CreatedAt time.Time`、`UpdatedAt time.Time`，由 GORM 按字段约定赋值，使用 UTC 时钟。 [GORM 模型约定](https://gorm.io/docs/models.html) · [GORM NowFunc](https://gorm.io/docs/gorm_config.html#NowFunc)

Goose 迁移将两列声明为 `TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP`。直接 SQL 插入时可以省略两列，直接 SQL 更新时显式将 `updated_at` 设置为 `CURRENT_TIMESTAMP`。 [PostgreSQL 16 日期与时间类型](https://www.postgresql.org/docs/16/datatype-datetime.html)
