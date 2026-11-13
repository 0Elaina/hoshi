package com.nep.hoshi.common.pagination;

import com.nep.hoshi.common.api.ApiCode;
import com.nep.hoshi.common.exceptions.BusinessException;

public record PageQuery(long page, int pageSize) {
    private static final long DEFAULT_PAGE = 1;
    private static final int DEFAULT_PAGE_SIZE = 20;
    private static final int MAX_PAGE_SIZE = 100;

    public PageQuery {
        if (page < 1 || pageSize < 1 || pageSize > MAX_PAGE_SIZE || page - 1 > Long.MAX_VALUE / pageSize) {
            throw new BusinessException(ApiCode.INVALID_ARGUMENT);
        }
    }

    public static PageQuery parse(String page, String pageSize) {
        try {
            return new PageQuery(
                    page == null ? DEFAULT_PAGE : Long.parseLong(page),
                    pageSize == null ? DEFAULT_PAGE_SIZE : Integer.parseInt(pageSize));
        } catch (NumberFormatException exception) {
            throw new BusinessException(ApiCode.INVALID_ARGUMENT);
        }
    }

    public long offset() {
        return (page - 1) * pageSize;
    }
}
