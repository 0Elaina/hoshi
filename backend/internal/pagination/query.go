package pagination

import (
	"math"

	"hoshi/backend/internal/apicode"
	"hoshi/backend/internal/apperr"
)

const (
	DefaultPage     = 1
	DefaultPageSize = 20
	MaxPageSize     = 100
)

type Query struct {
	Page     int
	PageSize int
}

func New(page, pageSize int) (Query, error) {
	if page < 1 || pageSize < 1 || pageSize > MaxPageSize || (page-1) > math.MaxInt/pageSize {
		return Query{}, apperr.New(apicode.InvalidArgument)
	}
	return Query{Page: page, PageSize: pageSize}, nil
}

func (q Query) Offset() int {
	return (q.Page - 1) * q.PageSize
}
