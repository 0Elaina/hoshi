# 管理端账号接口

## GET /api/v1/admin/accounts/me

校验 Bearer 访问令牌并查询当前已激活管理员账号的基本信息。

**请求参数**

| 字段 | 类型 | 位置(body/query/path/header) | 必填 | 说明（枚举须写全映射） |
| --- | --- | --- | --- | --- |
| `Authorization` | `string` | header | ✅ | `Bearer <accessToken>` |

**响应示例**

响应头包含 `Cache-Control: no-store`。`accountType` 取值：`admin`=管理员、`user`=普通用户（当前管理端接口仅成功返回 `admin`）；`role` 取值：`admin`=管理员、`user`=普通用户。

```json
{
  "data": {
    "id": "1",
    "username": "admin",
    "nickname": "管理员",
    "accountType": "admin",
    "role": "admin"
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
| 403 | `ACCESS_DENIED` |
| 403 | `ACCOUNT_UNAVAILABLE` |
