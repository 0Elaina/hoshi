package apicode

import "net/http"

// Code describes the HTTP status, stable business code, and default public message.
type Code struct {
	httpStatus int
	value      string
	message    string
}

func New(httpStatus int, value, message string) Code {
	return Code{httpStatus: httpStatus, value: value, message: message}
}

func (c Code) HTTPStatus() int {
	return c.httpStatus
}

func (c Code) Value() string {
	return c.value
}

func (c Code) Message() string {
	return c.message
}

var (
	Success          = New(http.StatusOK, "SUCCESS", "响应成功")
	Created          = New(http.StatusCreated, Success.Value(), Success.Message())
	InvalidArgument  = New(http.StatusBadRequest, "INVALID_ARGUMENT", "请求参数无效")
	RouteNotFound    = New(http.StatusNotFound, "ROUTE_NOT_FOUND", "请求路径不存在")
	MethodNotAllowed = New(http.StatusMethodNotAllowed, "METHOD_NOT_ALLOWED", "请求方法不受支持")
	InternalError    = New(http.StatusInternalServerError, "INTERNAL_ERROR", "服务器内部错误")
)
