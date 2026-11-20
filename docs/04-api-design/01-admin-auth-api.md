# 管理端认证接口

## POST /api/v1/admin/auth/login

校验请求来源、登录限流与管理员凭据，创建会话并在响应体返回访问令牌，同时通过 HttpOnly Cookie 下发刷新令牌。

**请求参数**

| 字段 | 类型 | 位置(body/query/path/header) | 必填 | 说明（枚举须写全映射） |
| --- | --- | --- | --- | --- |
| `Origin` | `string` | header | ✅ | 必须与服务端 `HOSHI_ADMIN_ORIGIN` 配置完全一致 |
| `username` | `string` | body | ✅ | 登录用户名，长度 1–32 |
| `password` | `string` | body | ✅ | 登录密码，长度 1–128，原样参与核验 |

**响应示例**

响应头包含 `Cache-Control: no-store` 与 `Set-Cookie: hoshi_admin_refresh=<refreshToken>; Path=/api/v1/admin/auth; Max-Age=86400; HttpOnly; SameSite=strict`（`HOSHI_APP_ENV=production` 时附加 `Secure`，省略 `Domain`）。

```json
{
  "data": {
    "accessToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "expiresIn": 300
  },
  "code": "SUCCESS",
  "message": "响应成功",
  "errors": []
}
```

**错误码**

| 状态码 | 错误码 |
| --- | --- |
| 400 | `INVALID_ARGUMENT` |
| 401 | `INVALID_CREDENTIALS` |
| 403 | `INVALID_AUTH_ORIGIN` |
| 429 | `LOGIN_RATE_LIMITED` |
| 503 | `AUTH_TEMPORARILY_UNAVAILABLE` |

## POST /api/v1/admin/auth/refresh

校验请求来源与刷新 Cookie，轮换 `jti` 后签发新的访问与刷新令牌，沿用原会话固定截止时间；旧刷新令牌重用将撤销整条会话。

**请求参数**

| 字段 | 类型 | 位置(body/query/path/header) | 必填 | 说明（枚举须写全映射） |
| --- | --- | --- | --- | --- |
| `Origin` | `string` | header | ✅ | 必须与服务端 `HOSHI_ADMIN_ORIGIN` 配置完全一致 |
| `hoshi_admin_refresh` | `string` | cookie | ❌ | 刷新令牌 Cookie；业务上必需，缺失或无效返回 `401 / INVALID_TOKEN` |

**响应示例**

响应头包含 `Cache-Control: no-store`。成功时通过 `Set-Cookie` 写入轮换后的 `hoshi_admin_refresh`（`Path=/api/v1/admin/auth; Max-Age=86400; HttpOnly; SameSite=strict`，`HOSHI_APP_ENV=production` 时附加 `Secure`，省略 `Domain`），会话保持登录时写入的固定 `expires_at`；旧 `jti` 重放、账号禁用或令牌无效时提交撤销并返回 `401 / INVALID_TOKEN` 且清除 Cookie；Origin 错误或 `5xx` 数据库异常保留原 Cookie。

```json
{
  "data": {
    "accessToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "expiresIn": 300
  },
  "code": "SUCCESS",
  "message": "响应成功",
  "errors": []
}
```

**错误码**

| 状态码 | 错误码 |
| --- | --- |
| 401 | `INVALID_TOKEN` |
| 403 | `INVALID_AUTH_ORIGIN` |

## POST /api/v1/admin/auth/logout

按刷新 Cookie 对应的会话 `sid` 幂等撤销当前会话并清除 Cookie；Cookie 缺失、令牌无效或会话已撤销仍返回成功。

**请求参数**

| 字段 | 类型 | 位置(body/query/path/header) | 必填 | 说明（枚举须写全映射） |
| --- | --- | --- | --- | --- |
| `Origin` | `string` | header | ✅ | 必须与服务端 `HOSHI_ADMIN_ORIGIN` 配置完全一致 |
| `hoshi_admin_refresh` | `string` | cookie | ❌ | 刷新令牌 Cookie；签名有效且账号归属匹配时按 `sid` 撤销会话（允许已轮换的旧 `jti`） |

**响应示例**

响应头包含 `Cache-Control: no-store`。用例成功后通过 `Set-Cookie` 清除 `hoshi_admin_refresh`；数据库异常走全局 `500 / INTERNAL_ERROR` 并保留 Cookie 供重试。

```json
{
  "data": null,
  "code": "SUCCESS",
  "message": "响应成功",
  "errors": []
}
```

**错误码**

| 状态码 | 错误码 |
| --- | --- |
| 403 | `INVALID_AUTH_ORIGIN` |
