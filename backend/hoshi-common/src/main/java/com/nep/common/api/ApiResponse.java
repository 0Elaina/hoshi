package com.nep.common.api;

import com.fasterxml.jackson.annotation.JsonInclude;

import lombok.AccessLevel;
import lombok.AllArgsConstructor;
import lombok.Getter;

@Getter
@AllArgsConstructor(access = AccessLevel.PRIVATE)
@JsonInclude(JsonInclude.Include.ALWAYS)
public final class ApiResponse<T> {

    private final T data;
    private final String code;
    private final String message;

    public static <T> ApiResponse<T> success(T data) {
        return new ApiResponse<>(data, ApiCode.SUCCESS.getCode(), ApiCode.SUCCESS.getMessage());
    }

    public static ApiResponse<Void> success() {
        return success(null);
    }

    public static ApiResponse<Void> error(ApiCode apiCode, String message) {
        return new ApiResponse<>(null, apiCode.getCode(), message);
    }

    public static ApiResponse<Void> error(ApiCode apiCode) {
        return error(apiCode, apiCode.getMessage());
    }
}
