package httpapi

import (
	"github.com/gin-gonic/gin"

	"hoshi/backend/internal/apicode"
)

type Response[T any] struct {
	Data    T      `json:"data"`
	Code    string `json:"code"`
	Message string `json:"message"`
}

func Success[T any](c *gin.Context, data T) {
	writeResponse(c, apicode.Success, data, "")
}

func Created[T any](c *gin.Context, data T) {
	writeResponse(c, apicode.Created, data, "")
}

func writeResponse[T any](c *gin.Context, code apicode.Code, data T, message string) {
	if message == "" {
		message = code.Message()
	}
	c.JSON(code.HTTPStatus(), Response[T]{
		Data:    data,
		Code:    code.Value(),
		Message: message,
	})
}
