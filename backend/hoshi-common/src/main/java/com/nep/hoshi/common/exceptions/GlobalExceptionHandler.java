package com.nep.hoshi.common.exceptions;

import java.util.ArrayList;
import java.util.List;

import com.nep.hoshi.common.api.ApiCode;
import com.nep.hoshi.common.api.ApiResponse;
import com.nep.hoshi.common.api.FieldError;
import org.jspecify.annotations.Nullable;
import org.springframework.context.MessageSourceResolvable;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.method.ParameterErrors;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.context.request.WebRequest;
import org.springframework.web.method.annotation.HandlerMethodValidationException;
import org.springframework.web.servlet.mvc.method.annotation.ResponseEntityExceptionHandler;

@RestControllerAdvice
public class GlobalExceptionHandler extends ResponseEntityExceptionHandler {
    @ExceptionHandler(BusinessException.class)
    public @Nullable ResponseEntity<Object> handleBusinessException(BusinessException exception, WebRequest request) {
        ApiCode code = exception.getApiCode();
        HttpStatus status = code.httpStatus();
        if (!status.isError()) {
            return handleUnexpectedException(exception, request);
        }
        String message = code.message();
        if (status.is5xxServerError()) {
            logger.error("处理请求失败", exception);
        } else if (exception.getMessage() != null && !exception.getMessage().isBlank()) {
            message = exception.getMessage();
        }
        return super.handleExceptionInternal(exception, ApiResponse.error(code, message),
                HttpHeaders.EMPTY, status, request);
    }

    @ExceptionHandler(Exception.class)
    public @Nullable ResponseEntity<Object> handleUnexpectedException(Exception exception, WebRequest request) {
        return handleExceptionInternal(exception, null, HttpHeaders.EMPTY, HttpStatus.INTERNAL_SERVER_ERROR, request);
    }

    @Override
    protected @Nullable ResponseEntity<Object> handleExceptionInternal(
            Exception exception, @Nullable Object body, HttpHeaders headers, HttpStatusCode status, WebRequest request) {
        ApiCode code = switch (status.value()) {
            case 400 -> ApiCode.INVALID_ARGUMENT;
            case 404 -> ApiCode.ROUTE_NOT_FOUND;
            case 405 -> ApiCode.METHOD_NOT_ALLOWED;
            default -> status.is4xxClientError() ? ApiCode.HTTP_ERROR : ApiCode.INTERNAL_ERROR;
        };
        if (status.is5xxServerError()) {
            logger.error("处理请求失败", exception);
        }
        List<FieldError> errors = status.value() == 400 ? validationErrors(exception) : List.of();
        return super.handleExceptionInternal(exception, ApiResponse.error(code, code.message(), errors),
                headers, status, request);
    }

    private static List<FieldError> validationErrors(Exception exception) {
        if (exception instanceof MethodArgumentNotValidException invalidBody) {
            return invalidBody.getBindingResult().getFieldErrors().stream()
                    .map(GlobalExceptionHandler::fieldError)
                    .toList();
        }
        if (exception instanceof HandlerMethodValidationException invalidMethod) {
            List<FieldError> errors = new ArrayList<>();
            for (var result : invalidMethod.getParameterValidationResults()) {
                if (result instanceof ParameterErrors beanErrors) {
                    beanErrors.getFieldErrors().stream().map(GlobalExceptionHandler::fieldError).forEach(errors::add);
                } else {
                    String name = result.getMethodParameter().getParameterName();
                    if (name != null) {
                        for (var error : result.getResolvableErrors()) {
                            errors.add(new FieldError(name, publicMessage(error)));
                        }
                    }
                }
            }
            return List.copyOf(errors);
        }
        return List.of();
    }

    private static FieldError fieldError(org.springframework.validation.FieldError error) {
        String message = error.isBindingFailure() ? ApiCode.INVALID_ARGUMENT.message() : publicMessage(error);
        return new FieldError(error.getField(), message);
    }

    private static String publicMessage(MessageSourceResolvable error) {
        String message = error.getDefaultMessage();
        return message == null || message.isBlank() ? ApiCode.INVALID_ARGUMENT.message() : message;
    }
}
