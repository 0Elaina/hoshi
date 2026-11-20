# 认证与会话表

## auth_sessions 表

存储管理员和用户的认证会话、当前刷新令牌标识与到期或撤销状态。

**字段**

| 字段名 | 类型 | 约束(PK/FK/UNIQUE/NOT NULL/DEFAULT) | 说明（枚举须写全映射） |
| --- | --- | --- | --- |
| `id` | `VARCHAR(36)` | `PK, NOT NULL` | 会话主键，应用生成 UUID v4 字符串，对应刷新 JWT 的 `sid` |
| `account_id` | `BIGINT` | `FK(user_accounts.id), NOT NULL` | 所属账号 ID，外键约束 `ON DELETE RESTRICT` |
| `refresh_jti` | `VARCHAR(36)` | `NOT NULL` | 当前有效刷新令牌 ID，应用生成独立 UUID v4 字符串，对应刷新 JWT 的 `jti` |
| `expires_at` | `TIMESTAMPTZ` | `NOT NULL` | 会话过期时间（UTC），由应用按对应账号类型 TTL 写入 |
| `revoked_at` | `TIMESTAMPTZ` | `NULL` | 会话撤销时间（UTC），未撤销时为空 |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL, DEFAULT CURRENT_TIMESTAMP` | 创建时间（UTC） |
| `updated_at` | `TIMESTAMPTZ` | `NOT NULL, DEFAULT CURRENT_TIMESTAMP` | 更新时间（UTC） |

**索引**

| 索引名 | 类型 | 字段 | 理由（必须说明具体查询场景） |
| --- | --- | --- | --- |
| `pk_auth_sessions` | 主键 | `id` | 刷新令牌轮换与登出时按 `sid` 精确查询会话记录 |
| `ix_auth_sessions_account_id` | 普通 | `account_id` | 按账号 ID 查询或批量撤销该账号的认证会话 |
| `ix_auth_sessions_expires_at` | 普通 | `expires_at` | 按过期时间范围检索并清理已到期的会话记录 |

**关系**

| 关系 | 目标表 | 外键字段 | 说明 |
| --- | --- | --- | --- |
| N:1 | `user_accounts` | `account_id` | 会话所属账号，存在关联会话时禁止直接删除账号 |

**建表 SQL**

```sql
CREATE TABLE auth_sessions (
    id VARCHAR(36) NOT NULL,
    account_id BIGINT NOT NULL,
    refresh_jti VARCHAR(36) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_auth_sessions PRIMARY KEY (id),
    CONSTRAINT fk_auth_sessions_account_id_user_accounts FOREIGN KEY (account_id)
        REFERENCES user_accounts (id) ON DELETE RESTRICT
);

CREATE INDEX ix_auth_sessions_account_id ON auth_sessions (account_id);
CREATE INDEX ix_auth_sessions_expires_at ON auth_sessions (expires_at);
```
