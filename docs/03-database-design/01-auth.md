# 认证模块数据库设计

## auth_sessions 表

存储用户登录认证会话及刷新令牌（Refresh Token）生命周期状态。

**字段**

| 字段名 | 类型 | 约束(PK/FK/UNIQUE/NOT NULL/DEFAULT) | 说明（枚举须写全映射） |
| --- | --- | --- | --- |
| id | BIGINT | PK, GENERATED ALWAYS AS IDENTITY | 会话主键 ID |
| user_id | BIGINT | FK, NOT NULL | 关联的用户账号 ID |
| client_type | VARCHAR(16) | NOT NULL | 客户端类型：ADMIN=管理端 |
| current_refresh_jti | VARCHAR(36) | NOT NULL | 当前有效的刷新令牌唯一标识（UUID 字符串） |
| expires_at | TIMESTAMPTZ | NOT NULL | 会话绝对过期时间（UTC） |
| revoked_at | TIMESTAMPTZ | 允许 NULL | 会话主动撤销时间（UTC），未撤销时为 NULL |
| created_at | TIMESTAMPTZ | NOT NULL | 会话创建时间（UTC） |
| updated_at | TIMESTAMPTZ | NOT NULL | 会话最近活跃或刷新时间（UTC） |

**索引**

| 索引名 | 类型 | 字段 | 理由（必须说明具体查询场景） |
| --- | --- | --- | --- |
| auth_sessions_pkey | 主键 (B-tree) | id | 刷新令牌时根据会话 ID 定位记录 |
| idx_auth_sessions_user_id | 普通 (B-tree) | user_id | 用户修改密码、重置凭证或封禁时，批量查询并撤销该用户的全部有效会话 |
| idx_auth_sessions_expires_at | 普通 (B-tree) | expires_at | 后台定时任务清理已过期的失效会话记录 |

**关系**

| 关系 | 目标表 | 外键字段 | 说明 |
| --- | --- | --- | --- |
| N:1 | users | user_id | 关联用户账号；删除或修改用户时 RESTRICT，禁止级联物理删除 |

**建表 SQL**

```sql
CREATE TABLE auth_sessions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id BIGINT NOT NULL,
    client_type VARCHAR(16) NOT NULL,
    current_refresh_jti VARCHAR(36) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_auth_sessions_user FOREIGN KEY (user_id) REFERENCES users (id) ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE INDEX idx_auth_sessions_user_id ON auth_sessions (user_id);
CREATE INDEX idx_auth_sessions_expires_at ON auth_sessions (expires_at);

COMMENT ON TABLE auth_sessions IS '认证会话表';
COMMENT ON COLUMN auth_sessions.id IS '会话ID，自增主键';
COMMENT ON COLUMN auth_sessions.user_id IS '关联用户ID';
COMMENT ON COLUMN auth_sessions.client_type IS '客户端类型：ADMIN=管理端';
COMMENT ON COLUMN auth_sessions.current_refresh_jti IS '当前有效的刷新令牌唯一标识（UUID）';
COMMENT ON COLUMN auth_sessions.expires_at IS '会话过期时间（UTC）';
COMMENT ON COLUMN auth_sessions.revoked_at IS '会话主动撤销时间（UTC），未撤销为NULL';
COMMENT ON COLUMN auth_sessions.created_at IS '创建时间（UTC）';
COMMENT ON COLUMN auth_sessions.updated_at IS '更新时间（UTC）';
```

