package httpapi

import (
	"net/url"
	"strconv"

	"github.com/gin-gonic/gin"

	"hoshi/backend/internal/apicode"
	"hoshi/backend/internal/apperr"
	"hoshi/backend/internal/pagination"
)

type PageData[T any] struct {
	Items    []T   `json:"items"`
	Total    int64 `json:"total"`
	Page     int   `json:"page"`
	PageSize int   `json:"pageSize"`
}

func BindPage(c *gin.Context) (pagination.Query, error) {
	values, err := url.ParseQuery(c.Request.URL.RawQuery)
	if err != nil {
		return pagination.Query{}, apperr.New(apicode.InvalidArgument)
	}
	page, err := queryInt(values, "page", pagination.DefaultPage)
	if err != nil {
		return pagination.Query{}, err
	}
	pageSize, err := queryInt(values, "pageSize", pagination.DefaultPageSize)
	if err != nil {
		return pagination.Query{}, err
	}
	return pagination.New(page, pageSize)
}

func NewPageData[T any](query pagination.Query, items []T, total int64) PageData[T] {
	if items == nil {
		items = []T{}
	}
	return PageData[T]{Items: items, Total: total, Page: query.Page, PageSize: query.PageSize}
}

func queryInt(values url.Values, key string, defaultValue int) (int, error) {
	if !values.Has(key) {
		return defaultValue, nil
	}
	value, err := strconv.Atoi(values.Get(key))
	if err != nil {
		return 0, apperr.New(apicode.InvalidArgument)
	}
	return value, nil
}
