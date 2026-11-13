package com.nep.hoshi.common.exceptions;

import com.nep.hoshi.common.api.ApiCode;

import lombok.Getter;

@Getter
public class BusinessException extends RuntimeException {
    private final ApiCode apiCode;

    public BusinessException(ApiCode apiCode, String message) {
        super(message);
        this.apiCode = apiCode;
    }

    public BusinessException(ApiCode apiCode) {
        this(apiCode, apiCode.message());
    }
}
