package com.nep.common.api;

import org.springframework.http.HttpStatus;

import lombok.AllArgsConstructor;
import lombok.Getter;

@Getter
@AllArgsConstructor
public final class ApiCode {

    private final HttpStatus httpStatus;
    private final String code;
    private final String message;

    public static final ApiCode SUCCESS = new ApiCode(HttpStatus.OK, "SUCCESS", "响应成功");
    public static final ApiCode BAD_REQUEST = new ApiCode(HttpStatus.BAD_REQUEST, "BAD_REQUEST", "请求参数有误");
    public static final ApiCode PARAM_VALIDATION_FAILED = new ApiCode(HttpStatus.BAD_REQUEST,
            "PARAM_VALIDATION_FAILED", "参数校验未通过");
    public static final ApiCode UNAUTHORIZED = new ApiCode(HttpStatus.UNAUTHORIZED, "UNAUTHORIZED", "请先登录");
    public static final ApiCode FORBIDDEN = new ApiCode(HttpStatus.FORBIDDEN, "FORBIDDEN", "无权执行此操作");
    public static final ApiCode NOT_FOUND = new ApiCode(HttpStatus.NOT_FOUND, "NOT_FOUND", "请求的资源不存在");
    public static final ApiCode METHOD_NOT_ALLOWED = new ApiCode(HttpStatus.METHOD_NOT_ALLOWED,
            "METHOD_NOT_ALLOWED", "请求方法不支持");
    public static final ApiCode NOT_ACCEPTABLE = new ApiCode(HttpStatus.NOT_ACCEPTABLE,
            "NOT_ACCEPTABLE", "无法提供请求要求的响应格式");
    public static final ApiCode CONFLICTING_DATA = new ApiCode(HttpStatus.CONFLICT,
            "CONFLICTING_DATA", "数据冲突，请检查后重试");
    public static final ApiCode CONTENT_TOO_LARGE = new ApiCode(HttpStatus.CONTENT_TOO_LARGE,
            "CONTENT_TOO_LARGE", "请求内容过大");
    public static final ApiCode UNSUPPORTED_MEDIA_TYPE = new ApiCode(HttpStatus.UNSUPPORTED_MEDIA_TYPE,
            "UNSUPPORTED_MEDIA_TYPE", "请求内容类型不支持");
    public static final ApiCode TOO_MANY_REQUESTS = new ApiCode(HttpStatus.TOO_MANY_REQUESTS,
            "TOO_MANY_REQUESTS", "请求过于频繁，请稍后重试");
    public static final ApiCode INTERNAL_SERVER_ERROR = new ApiCode(HttpStatus.INTERNAL_SERVER_ERROR,
            "INTERNAL_SERVER_ERROR", "服务器内部错误，请稍后重试");
    public static final ApiCode SERVICE_UNAVAILABLE = new ApiCode(HttpStatus.SERVICE_UNAVAILABLE,
            "SERVICE_UNAVAILABLE", "服务暂时不可用，请稍后重试");
}
