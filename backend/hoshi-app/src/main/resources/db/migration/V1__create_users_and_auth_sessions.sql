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