package httpserver

import (
	"net/http"

	"github.com/gin-gonic/gin"

	"hoshi/backend/internal/httpserver/httpapi"
)

func NewRouter() http.Handler {
	router := gin.New()
	_ = router.SetTrustedProxies(nil)
	router.Use(gin.Logger(), gin.CustomRecoveryWithWriter(nil, httpapi.Recover))
	router.HandleMethodNotAllowed = true
	router.NoRoute(httpapi.RouteNotFound)
	router.NoMethod(httpapi.MethodNotAllowed)
	return router
}
