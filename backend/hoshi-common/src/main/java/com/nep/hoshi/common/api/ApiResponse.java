package com.nep.hoshi.common.api;

import java.util.List;

public record ApiResponse<T>(
        T data,
        String code,
        String message,
        List<FieldError> errors) {

    public static <T> ApiResponse<T> success(T data) {
        return new ApiResponse<>(data, ApiCode.SUCCESS.code(), ApiCode.SUCCESS.message(), List.of());
    }

    public static ApiResponse<Void> success() {
        return success(null);
    }

    public static ApiResponse<Void> error(ApiCode apiCode, String message, List<FieldError> errors) {
        return new ApiResponse<>(null, apiCode.code(), message, errors);
    }

    public static ApiResponse<Void> error(ApiCode apiCode, String message) {
        return error(apiCode, message, List.of());
    }

    public static ApiResponse<Void> error(ApiCode apiCode) {
        return error(apiCode, apiCode.message(), List.of());
    }
}
