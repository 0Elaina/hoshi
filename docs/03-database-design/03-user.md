# 用户模块数据库设计

## users 表

存储系统用户账号与基础资料信息。

**字段**

| 字段名 | 类型 | 约束(PK/FK/UNIQUE/NOT NULL/DEFAULT) | 说明（枚举须写全映射） |
| --- | --- | --- | --- |
| id | BIGINT | PK, GENERATED ALWAYS AS IDENTITY | 用户主键 ID |
| username | VARCHAR(32) | NOT NULL, UNIQUE | 登录用户名 |
| password_hash | VARCHAR(255) | NOT NULL | 密码散列值 |
| nickname | VARCHAR(32) | NOT NULL | 显示昵称 |
| role | VARCHAR(16) | NOT NULL | 用户角色：USER=普通用户, ADMIN=管理员 |
| status | VARCHAR(16) | NOT NULL | 账号状态：ENABLED=启用, DISABLED=禁用 |
| created_at | TIMESTAMPTZ | NOT NULL | 账号创建时间（UTC） |
| updated_at | TIMESTAMPTZ | NOT NULL | 资料更新时间（UTC） |

**索引**

| 索引名 | 类型 | 字段 | 理由（必须说明具体查询场景） |
| --- | --- | --- | --- |
| uk_users_username | 唯一 | username | 登录凭据唯一定位用户，防止用户名重复注册 |
| idx_users_role_id | 普通 (B-tree) | role, id | 固定普通用户角色（role='USER'）后按 ID 倒序分页查询列表 |

**关系**

无外键关联。

**建表 SQL**

```sql
CREATE TABLE users (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username VARCHAR(32) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    nickname VARCHAR(32) NOT NULL,
    role VARCHAR(16) NOT NULL,
    status VARCHAR(16) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uk_users_username UNIQUE (username)
);

CREATE INDEX idx_users_role_id ON users (role, id);

COMMENT ON TABLE users IS '用户账号表';
COMMENT ON COLUMN users.id IS '用户ID，自增主键';
COMMENT ON COLUMN users.username IS '用户名';
COMMENT ON COLUMN users.password_hash IS '密码散列值';
COMMENT ON COLUMN users.nickname IS '用户昵称';
COMMENT ON COLUMN users.role IS '用户角色：USER=普通用户, ADMIN=管理员';
COMMENT ON COLUMN users.status IS '账号状态：ENABLED=启用, DISABLED=禁用';
COMMENT ON COLUMN users.created_at IS '创建时间（UTC）';
COMMENT ON COLUMN users.updated_at IS '更新时间（UTC）';
```

