# 全局错误码

客户端根据 HTTP 状态码和响应中的字符串 `code` 分支处理，`message` 用于展示。错误响应的 `data` 为 `null`。`errors` 为数组，字段校验失败时每项包含字符串 `field` 和 `message`，没有字段明细时为 `[]`。

公共 `ApiCode` 定义在 `hoshi-common`，包含 HTTP 状态码、字符串业务码和默认消息。业务模块用同一个类型声明专属码，并在对应接口文档中列出。同模块的 MVC 全局异常处理器将 `BusinessException` 转成统一响应。`4xx` 业务错误可以指定公开消息。`5xx` 业务错误使用业务码定义的默认消息。MVC 框架异常保留状态和响应头，未单独映射的 `4xx` 使用 `HTTP_ERROR`，框架和未处理的 `5xx` 使用 `INTERNAL_ERROR`。Spring Security 过滤链使用框架默认响应。

| 状态码 | 错误码 | 默认消息 | 说明 |
| --- | --- | --- | --- |
| 400 | `INVALID_ARGUMENT` | 请求参数无效 | 请求参数格式或取值不符合接口约定 |
| 404 | `ROUTE_NOT_FOUND` | 请求路径不存在 | 请求路径未匹配到已注册路由 |
| 405 | `METHOD_NOT_ALLOWED` | 请求方法不受支持 | 路径存在，允许的方法由 `Allow` 响应头给出 |
| 其他 4xx | `HTTP_ERROR` | 请求处理失败 | Spring MVC 返回的其他客户端错误 |
| 500 | `INTERNAL_ERROR` | 服务器内部错误 | 服务端记录异常，客户端收到通用提示 |
