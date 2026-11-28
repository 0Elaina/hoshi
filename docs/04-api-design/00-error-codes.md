# 全局错误码

客户端根据 HTTP 状态码和响应中的字符串 `code` 分支处理，`message` 用于展示。错误响应的 `data` 为 `null`。`errors` 为数组，字段校验失败时每项包含字符串 `field` 和 `message`，没有字段明细时为 `[]`。

公共 `ApiCode` 定义在 `hoshi.shared.http.api_code`，包含 HTTP 状态码、字符串业务码和默认消息。业务模块用同一类型声明专属码，并在对应接口文档中列出。FastAPI 全局异常处理器将 `BusinessException` 转为统一响应。`4xx` 业务错误可以指定公开消息，`5xx` 业务错误使用业务码的默认消息。框架 HTTP 异常保留状态和响应头。未单独映射的 `4xx` 使用 `HTTP_ERROR`，框架及未处理的 `5xx` 使用 `INTERNAL_ERROR`。

| 状态码 | 错误码 | 默认消息 | 说明 |
| --- | --- | --- | --- |
| 400 | `INVALID_ARGUMENT` | 请求参数无效 | 请求参数格式或取值不符合接口约定 |
| 404 | `ROUTE_NOT_FOUND` | 请求路径不存在 | 请求路径未匹配到已注册路由 |
| 405 | `METHOD_NOT_ALLOWED` | 请求方法不受支持 | 路径存在，允许的方法由 `Allow` 响应头给出 |
| 其他 4xx | `HTTP_ERROR` | 请求处理失败 | 框架返回的其他客户端错误 |
| 500 | `INTERNAL_ERROR` | 服务器内部错误 | 服务端记录异常，客户端收到通用提示 |
| 502 | `STORAGE_BAD_GATEWAY` | 对象存储服务响应异常 | 对象存储上游返回未归入不可用的 SDK 或协议错误 |
| 503 | `STORAGE_UNAVAILABLE` | 对象存储服务暂时不可用 | 对象存储未启用、连接失败/中断/超时，或上游返回 `408`/`429`/`500`/`502`/`503`/`504`、`SlowDown`/`RequestTimeout`/`ServiceUnavailable` |
| 503 | `SERVICE_UNAVAILABLE` | 服务暂时不可用，请稍后重试 | 共享依赖（如 Redis 限流）发生暂态故障导致请求无法受理 |

## 认证与账号通用业务错误码

以下业务码供认证链路及受保护入口复用，各接口仍须在所属接口文档的错误码表显式列出：

| 状态码 | 错误码 | 默认消息 | 所属模块与适用场景 |
| --- | --- | --- | --- |
| 401 | `INVALID_TOKEN` | 认证令牌无效或已过期 | `auth` 模块；Bearer 鉴权缺失、令牌无效/过期或误用刷新令牌时复用此码并附带 `WWW-Authenticate: Bearer`，刷新接口同步按规则撤销会话与清除 Cookie |
| 403 | `ACCESS_DENIED` | 无权访问当前入口 | `auth` 模块；访问令牌有效但声明的账号类型不满足当前入口要求（如普通用户令牌访问管理端受保护路由） |
| 403 | `ACCOUNT_UNAVAILABLE` | 当前账号不可用 | `user` 模块；访问令牌有效但数据库中账号已删除、已禁用或账号类型已发生变更 |

## 文件服务通用业务错误码

以下业务码定义在 `hoshi.modules.files.constants.FileApiCode`，供各接入文件直传、确认与规格申请的业务接口复用：

| 状态码 | 错误码 | 默认消息 | 所属模块与适用场景 |
| --- | --- | --- | --- |
| 404 | `FILE_ASSET_NOT_FOUND` | 文件资产不存在 | `files` 模块；资产不存在或不属于当前操作账号 |
| 409 | `FILE_UPLOAD_NOT_RECEIVED` | 尚未收到上传文件 | `files` 模块；确认上传时暂存对象尚不存在，保留待确认状态 |
| 409 | `FILE_UPLOAD_METADATA_MISMATCH` | 上传文件元信息与登记不符 | `files` 模块；暂存对象大小或 MIME 与登记不符（先落库 `upload_rejected` 再返回）或资产已被拒绝 |
| 409 | `FILE_ASSET_NOT_READY` | 文件资产尚未就绪 | `files` 模块；对尚未达到 `ready` 的资产申请衍生规格 |
| 409 | `FILE_VARIANT_WITHDRAWN` | 目标文件规格已撤回 | `files` 模块；规格并发申请冲突后加锁前该规格已被撤回，需重新确认授权 |
| 410 | `FILE_UPLOAD_EXPIRED` | 文件上传确认窗口已过期 | `files` 模块；待确认资产已超过 15 分钟确认截止时间 |
| 413 | `FILE_UPLOAD_TOO_LARGE` | 上传文件大小超出限制 | `files` 模块；声明字节数超过该媒体类型上限（图片 10 MiB） |
| 415 | `FILE_UPLOAD_UNSUPPORTED_MEDIA` | 不支持的文件媒体类型 | `files` 模块；媒体大类或 MIME 不在只读允许集合内 |
| 429 | `FILE_UPLOAD_RATE_LIMITED` | 上传请求过于频繁，请稍后重试 | `files` 模块；账号或来源 IP 触发直传授权限流，响应头附带 `Retry-After`（秒） |
