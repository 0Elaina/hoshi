# API 通用约定

## 响应结构

JSON 接口显式返回 `ApiResponse<T>`，通过工厂方法创建成功或错误响应。HTTP 状态码表达请求处理结果，响应体中的字符串业务码表达具体含义。

| 字段 | Java 类型 | JSON 类型 | 空值约定 | 说明 |
| --- | --- | --- | --- | --- |
| data | T | 由接口定义 | 可以为 null，字段始终保留 | 成功时承载接口数据；无返回数据或发生错误时为 null |
| code | String | string | 非空 | 成功为 SUCCESS；错误使用已定义的业务码 |
| message | String | string | 非空 | 可向用户展示的提示，不承载数据库或系统异常原文 |

无返回数据的成功响应示例：

```json
{
  "data": null,
  "code": "SUCCESS",
  "message": "响应成功"
}
```

参数校验失败时 HTTP 状态为 400，响应示例：

```json
{
  "data": null,
  "code": "PARAM_VALIDATION_FAILED",
  "message": "页码不能小于1"
}
```

`ApiResponse.success(data)` 返回带数据的成功响应，`success()` 返回无数据成功响应。`error(apiCode)` 使用默认错误提示，`error(apiCode, message)` 使用调用方提供的提示。

普通 Controller 显式返回成功响应；全局异常处理器生成错误响应，保留框架异常对应的 HTTP 状态和响应头。统一响应类通过 Jackson 注解保留空字段，使用 Boot 4 默认的 Jackson 3 集成。

## 业务码与异常

`com.nep.common.api.ApiCode` 是包含 `HttpStatus httpStatus`、`String code`、`String message` 的不可变值类。三个成员均按非空契约使用。通用码在 common 定义，具体业务模块维护自己的码常量，类型仍为 `ApiCode`；所有码归档到[全局错误码表](00-error-codes.md)。

业务代码抛出 `BusinessException`，携带 `ApiCode` 及可向用户展示的 message。未指定自定义提示时使用业务码的默认 message。

common 中的 `com.nep.common.exception.GlobalExceptionHandler` 继承 Spring 的 `ResponseEntityExceptionHandler`，统一转换 MVC 异常。DTO 校验、方法入参校验及约束校验失败使用 `PARAM_VALIDATION_FAILED`，只返回一条非空校验提示，`data` 为 null。返回值约束失败属于服务端错误，按 HTTP 500 处理。

唯一键冲突使用 `CONFLICTING_DATA`，HTTP 状态为 409；其他未专门映射的异常使用通用 HTTP 500 提示。服务端错误记录异常堆栈，响应不包含异常原文。该异常处理器处理进入 Spring MVC 异常处理链的错误，安全过滤器等组件接入时需单独对齐响应。

## 分页请求

`com.nep.common.page.PageQuery` 是分页查询参数基类。分页 Controller 参数须启用 Jakarta Validation，例如使用 `@Valid`；具体筛选条件由接口自己的查询类型定义。

| 字段 | Java 类型 | 请求类型 | 必填 | 默认值 | 校验 |
| --- | --- | --- | --- | --- | --- |
| pageNum | Integer | int | 否 | 1 | 绑定后不能为空，且大于等于 1 |
| pageSize | Integer | int | 否 | 20 | 绑定后不能为空，且在 1 至 100 之间 |

页码或每页条数非法时返回 HTTP 400。`PageQuery.toPage()` 创建 MyBatis-Plus 分页对象，不替代请求参数校验。

排序字段、排序方向和默认排序由具体接口定义；通用分页参数不接受任意数据库列名。

## 分页响应

`com.nep.common.page.PageResult<T>` 作为 `ApiResponse` 的 data，隔离前端契约与 MyBatis-Plus 的分页实现。

| 字段 | Java 类型 | JSON 类型 | 空值约定 | 说明 |
| --- | --- | --- | --- | --- |
| records | List<T> | array | 非空，无记录时为空数组 | 本页数据，元素结构由接口定义 |
| total | long | number | 非空 | 满足查询条件的总记录数 |
| pageNum | long | number | 非空 | 当前请求页码 |
| pageSize | long | number | 非空 | 当前每页条数 |

空数据响应示例：

```json
{
  "data": {
    "records": [],
    "total": 0,
    "pageNum": 1,
    "pageSize": 20
  },
  "code": "SUCCESS",
  "message": "响应成功"
}
```

`PageResult.from(IPage<T>)` 提取四个分页字段。接口需要将实体转换成响应类型时，先完成记录转换，再生成分页响应。请求页码超过末页时保留请求页码，返回空 records，不跳回第一页。

参考依据：[Spring MVC 异常响应](https://docs.spring.io/spring-framework/reference/web/webmvc/mvc-ann-rest-exceptions.html)、[Spring MVC 校验](https://docs.spring.io/spring-framework/reference/web/webmvc/mvc-controller/ann-validation.html)、[MyBatis-Plus 分页插件](https://baomidou.com/plugins/pagination/)。
