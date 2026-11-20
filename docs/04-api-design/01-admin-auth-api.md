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
