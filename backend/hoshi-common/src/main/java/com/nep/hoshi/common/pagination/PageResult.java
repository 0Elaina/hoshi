package com.nep.hoshi.common.pagination;

import java.util.List;

public record PageResult<T>(List<T> items, long total, long page, int pageSize) {
    public PageResult {
        items = items == null ? List.of() : List.copyOf(items);
    }

    public static <T> PageResult<T> of(PageQuery query, List<T> items, long total) {
        return new PageResult<>(items, total, query.page(), query.pageSize());
    }
}
