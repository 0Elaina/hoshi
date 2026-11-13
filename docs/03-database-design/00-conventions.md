# 数据库通用约定

## 创建与更新时间

需要审计时间戳的表使用 `created_at`、`updated_at`。Java 实体使用 `OffsetDateTime`，应用以 UTC 填充。需要 MyBatis-Plus 自动填充的实体，将 `createdAt` 声明为 `FieldFill.INSERT`，将 `updatedAt` 声明为 `FieldFill.INSERT_UPDATE`。共用填充器为未赋值的字段填入当前 UTC 时间。更新时，实体已带有 `updatedAt` 则沿用该值。

Flyway SQL 将两列声明为 `TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP`。直接 SQL 插入时可使用数据库默认值，直接 SQL 更新时显式将 `updated_at` 设置为 `CURRENT_TIMESTAMP`。 [PostgreSQL 16 日期与时间类型](https://www.postgresql.org/docs/16/datatype-datetime.html) · [MyBatis-Plus 自动填充](https://baomidou.com/en/guides/auto-fill-field/)
