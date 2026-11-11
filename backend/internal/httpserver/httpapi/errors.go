package httpapi

import (
	"errors"
	"log/slog"
	"net/http"
	"runtime/debug"

	"github.com/gin-gonic/gin"

	"hoshi/backend/internal/apicode"
	"hoshi/backend/internal/apperr"
)

func Error(c *gin.Context, err error) {
	code := apicode.InternalError
	var publicMessage string
	if appErr, ok := errors.AsType[*apperr.Error](err); ok && appErr != nil {
		declared := appErr.APICode()
		status := declared.HTTPStatus()
		if status >= http.StatusBadRequest && status < 600 && declared.Value() != "" {
			code = declared
			if status < http.StatusInternalServerError {
				publicMessage = appErr.PublicMessage()
			}
		}
	}
	if code.HTTPStatus() >= http.StatusInternalServerError {
		slog.ErrorContext(c.Request.Context(), "HTTP request failed",
			"method", c.Request.Method, "route", c.FullPath(), "error", err)
	}
	writeError(c, code, publicMessage)
}

func RouteNotFound(c *gin.Context) {
	writeError(c, apicode.RouteNotFound, "")
}

func MethodNotAllowed(c *gin.Context) {
	writeError(c, apicode.MethodNotAllowed, "")
}

func Recover(c *gin.Context, recovered any) {
	slog.ErrorContext(c.Request.Context(), "panic in HTTP request",
		"method", c.Request.Method, "route", c.FullPath(),
		"panic", recovered, "stack", string(debug.Stack()))
	writeError(c, apicode.InternalError, "")
}

func writeError(c *gin.Context, code apicode.Code, message string) {
	c.Abort()
	if !c.Writer.Written() {
		writeResponse[any](c, code, nil, message)
	}
}
