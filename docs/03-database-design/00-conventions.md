# 数据库通用约定

## 创建与更新时间

需要审计时间戳的表使用 `created_at`、`updated_at`。ORM 用 `DateTime(timezone=True)` 映射这两列，应用自行构造的时间使用带 UTC 时区的 `datetime`。Alembic 迁移将两列声明为 `TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP`。插入时可使用数据库默认值，更新时将 `updated_at` 设为当前时间。直接 SQL 更新使用 `CURRENT_TIMESTAMP`。 [PostgreSQL 16 日期与时间类型](https://www.postgresql.org/docs/16/datatype-datetime.html) · [SQLAlchemy 列默认值](https://docs.sqlalchemy.org/en/21/core/defaults.html)
