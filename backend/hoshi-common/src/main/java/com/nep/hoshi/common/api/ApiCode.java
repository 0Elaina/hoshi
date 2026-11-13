package com.nep.hoshi.common.api;

import org.springframework.http.HttpStatus;

public record ApiCode(
        HttpStatus httpStatus,
        String code,
        String message) {
    public static final ApiCode SUCCESS = new ApiCode(HttpStatus.OK, "SUCCESS", "响应成功");
    public static final ApiCode INVALID_ARGUMENT =
            new ApiCode(HttpStatus.BAD_REQUEST, "INVALID_ARGUMENT", "请求参数无效");
    public static final ApiCode ROUTE_NOT_FOUND =
            new ApiCode(HttpStatus.NOT_FOUND, "ROUTE_NOT_FOUND", "请求路径不存在");
    public static final ApiCode METHOD_NOT_ALLOWED =
            new ApiCode(HttpStatus.METHOD_NOT_ALLOWED, "METHOD_NOT_ALLOWED", "请求方法不受支持");
    public static final ApiCode HTTP_ERROR =
            new ApiCode(HttpStatus.BAD_REQUEST, "HTTP_ERROR", "请求处理失败");
    public static final ApiCode INTERNAL_ERROR =
            new ApiCode(HttpStatus.INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "服务器内部错误");
}
