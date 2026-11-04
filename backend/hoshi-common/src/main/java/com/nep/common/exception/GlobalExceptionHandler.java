package com.nep.common.exception;

import java.util.stream.Stream;
import java.util.stream.StreamSupport;

import org.springframework.context.MessageSourceResolvable;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.ResponseEntity;
import org.springframework.util.StringUtils;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.context.request.WebRequest;
import org.springframework.web.method.annotation.HandlerMethodValidationException;
import org.springframework.web.servlet.mvc.method.annotation.ResponseEntityExceptionHandler;

import com.nep.common.api.ApiCode;
import com.nep.common.api.ApiResponse;

import jakarta.validation.ConstraintViolationException;
import jakarta.validation.ElementKind;
import lombok.extern.slf4j.Slf4j;

@Slf4j
@RestControllerAdvice
public class GlobalExceptionHandler extends ResponseEntityExceptionHandler {

    @ExceptionHandler(BusinessException.class)
    ResponseEntity<Object> handleBusinessException(BusinessException ex, WebRequest request) {
        return handleExceptionInternal(ex, ApiResponse.error(ex.getApiCode(), ex.getMessage()),
                new HttpHeaders(), ex.getApiCode().getHttpStatus(), request);
    }

    @ExceptionHandler(DuplicateKeyException.class)
    ResponseEntity<Object> handleDuplicateKeyException(DuplicateKeyException ex, WebRequest request) {
        return handleExceptionInternal(ex, ApiResponse.error(ApiCode.CONFLICTING_DATA),
                new HttpHeaders(), ApiCode.CONFLICTING_DATA.getHttpStatus(), request);
    }

    @ExceptionHandler(ConstraintViolationException.class)
    ResponseEntity<Object> handleConstraintViolationException(ConstraintViolationException ex, WebRequest request) {
        boolean invalidReturnValue = ex.getConstraintViolations().stream()
                .anyMatch(violation -> StreamSupport.stream(violation.getPropertyPath().spliterator(), false)
                        .anyMatch(node -> node.getKind() == ElementKind.RETURN_VALUE));
        ApiCode apiCode = invalidReturnValue ? ApiCode.INTERNAL_SERVER_ERROR : ApiCode.PARAM_VALIDATION_FAILED;
        String message = invalidReturnValue ? apiCode.getMessage()
                : firstMessage(ex.getConstraintViolations().stream().map(violation -> violation.getMessage()));
        return handleExceptionInternal(ex, ApiResponse.error(apiCode, message),
                new HttpHeaders(), apiCode.getHttpStatus(), request);
    }

    @ExceptionHandler(Exception.class)
    ResponseEntity<Object> handleUnexpectedException(Exception ex, WebRequest request) {
        return handleExceptionInternal(ex, ApiResponse.error(ApiCode.INTERNAL_SERVER_ERROR),
                new HttpHeaders(), ApiCode.INTERNAL_SERVER_ERROR.getHttpStatus(), request);
    }

    @Override
    protected ResponseEntity<Object> handleMethodArgumentNotValid(MethodArgumentNotValidException ex,
            HttpHeaders headers, HttpStatusCode status, WebRequest request) {
        String message = firstMessage(ex.getAllErrors().stream().map(MessageSourceResolvable::getDefaultMessage));
        return handleExceptionInternal(ex, ApiResponse.error(ApiCode.PARAM_VALIDATION_FAILED, message),
                headers, status, request);
    }

    @Override
    protected ResponseEntity<Object> handleHandlerMethodValidationException(HandlerMethodValidationException ex,
            HttpHeaders headers, HttpStatusCode status, WebRequest request) {
        if (ex.isForReturnValue()) {
            return handleExceptionInternal(ex, ApiResponse.error(ApiCode.INTERNAL_SERVER_ERROR),
                    headers, status, request);
        }

        Stream<MessageSourceResolvable> errors = Stream.concat(
                ex.getParameterValidationResults().stream()
                        .flatMap(result -> result.getResolvableErrors().stream()),
                ex.getCrossParameterValidationResults().stream());
        String message = firstMessage(errors.map(MessageSourceResolvable::getDefaultMessage));
        return handleExceptionInternal(ex, ApiResponse.error(ApiCode.PARAM_VALIDATION_FAILED, message),
                headers, status, request);
    }

    @Override
    protected ResponseEntity<Object> handleExceptionInternal(Exception ex, Object body,
            HttpHeaders headers, HttpStatusCode statusCode, WebRequest request) {
        if (statusCode.is5xxServerError()) {
            log.error("请求处理失败，HTTP状态={}", statusCode.value(), ex);
        }
        return super.handleExceptionInternal(ex, body, headers, statusCode, request);
    }

    @Override
    protected ResponseEntity<Object> createResponseEntity(Object body, HttpHeaders headers,
            HttpStatusCode statusCode, WebRequest request) {
        Object responseBody = body instanceof ApiResponse<?> ? body : ApiResponse.error(resolveApiCode(statusCode));
        return new ResponseEntity<>(responseBody, headers, statusCode);
    }

    private static String firstMessage(Stream<String> messages) {
        return messages.filter(StringUtils::hasText).findFirst().orElse(ApiCode.PARAM_VALIDATION_FAILED.getMessage());
    }

    private static ApiCode resolveApiCode(HttpStatusCode status) {
        return switch (status.value()) {
            case 400 -> ApiCode.BAD_REQUEST;
            case 401 -> ApiCode.UNAUTHORIZED;
            case 403 -> ApiCode.FORBIDDEN;
            case 404 -> ApiCode.NOT_FOUND;
            case 405 -> ApiCode.METHOD_NOT_ALLOWED;
            case 406 -> ApiCode.NOT_ACCEPTABLE;
            case 409 -> ApiCode.CONFLICTING_DATA;
            case 413 -> ApiCode.CONTENT_TOO_LARGE;
            case 415 -> ApiCode.UNSUPPORTED_MEDIA_TYPE;
            case 429 -> ApiCode.TOO_MANY_REQUESTS;
            case 503 -> ApiCode.SERVICE_UNAVAILABLE;
            default -> status.is4xxClientError() ? ApiCode.BAD_REQUEST : ApiCode.INTERNAL_SERVER_ERROR;
        };
    }
}
