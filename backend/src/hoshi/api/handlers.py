import logging
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import cast

from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    ConnectionClosedError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ProxyConnectionError,
    ReadTimeoutError,
)
from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.utils import is_body_allowed_for_status_code
from starlette.exceptions import HTTPException
from starlette.types import ExceptionHandler

from hoshi.shared.http.api_code import ApiCode, CommonApiCode
from hoshi.shared.http.exception import BusinessException
from hoshi.shared.http.response import ApiResponse, FieldError

logger = logging.getLogger(__name__)

HTTP_ERROR_CODES: dict[int, ApiCode] = {
    status.HTTP_400_BAD_REQUEST: CommonApiCode.INVALID_ARGUMENT,
    status.HTTP_404_NOT_FOUND: CommonApiCode.ROUTE_NOT_FOUND,
    status.HTTP_405_METHOD_NOT_ALLOWED: CommonApiCode.METHOD_NOT_ALLOWED,
}

STORAGE_UNAVAILABLE_EXCEPTIONS = (
    EndpointConnectionError,
    ProxyConnectionError,
    ConnectionClosedError,
    ConnectTimeoutError,
    ReadTimeoutError,
)
STORAGE_UNAVAILABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
STORAGE_UNAVAILABLE_ERROR_CODES = frozenset(
    {"SlowDown", "RequestTimeout", "ServiceUnavailable"}
)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(
        BusinessException, cast(ExceptionHandler, handle_business_exception)
    )
    app.add_exception_handler(
        RequestValidationError, cast(ExceptionHandler, handle_request_validation)
    )
    app.add_exception_handler(
        HTTPException, cast(ExceptionHandler, handle_http_exception)
    )
    app.add_exception_handler(
        ClientError, cast(ExceptionHandler, handle_storage_exception)
    )
    app.add_exception_handler(
        BotoCoreError, cast(ExceptionHandler, handle_storage_exception)
    )
    app.add_exception_handler(Exception, handle_unexpected_exception)


def _error_response(
    api_code: ApiCode,
    *,
    message: str | None = None,
    errors: list[FieldError] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    response = ApiResponse.error(api_code, message, errors=errors)
    return JSONResponse(
        content=response.model_dump(mode="json"),
        status_code=api_code.http_status,
        headers=headers,
    )


def _validation_field(location: Sequence[str | int], error_type: str) -> str:
    if error_type == "json_invalid":
        return "body"
    return ".".join(map(str, location[1:] or location)) or "request"


def _classify_storage_exception(exc: ClientError | BotoCoreError) -> ApiCode:
    if isinstance(exc, STORAGE_UNAVAILABLE_EXCEPTIONS):
        return CommonApiCode.STORAGE_UNAVAILABLE

    if isinstance(exc, ClientError):
        response = exc.response
        error_code = (response.get("Error") or {}).get("Code")
        status_code = (response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
        if (
            status_code in STORAGE_UNAVAILABLE_STATUS_CODES
            or error_code in STORAGE_UNAVAILABLE_ERROR_CODES
        ):
            return CommonApiCode.STORAGE_UNAVAILABLE

    return CommonApiCode.STORAGE_BAD_GATEWAY


async def handle_request_validation(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = [
        FieldError(
            field=_validation_field(error["loc"], error["type"]),
            message=error["msg"],
        )
        for error in exc.errors()
    ]
    return _error_response(CommonApiCode.INVALID_ARGUMENT, errors=errors)


async def handle_business_exception(
    _request: Request, exc: BusinessException
) -> JSONResponse:
    api_code = exc.api_code
    if api_code.http_status >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        logger.error("Business operation failed with %s", api_code.code, exc_info=exc)
        return _error_response(api_code, headers=exc.headers)
    return _error_response(api_code, message=exc.message, headers=exc.headers)


async def handle_http_exception(_request: Request, exc: HTTPException) -> Response:
    if not is_body_allowed_for_status_code(exc.status_code):
        return Response(status_code=exc.status_code, headers=exc.headers)

    if exc.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        api_code = replace(CommonApiCode.INTERNAL_ERROR, http_status=exc.status_code)
    else:
        api_code = HTTP_ERROR_CODES.get(exc.status_code)
        if api_code is None:
            api_code = ApiCode(exc.status_code, "HTTP_ERROR", "请求处理失败")

    return _error_response(api_code, headers=exc.headers)


async def handle_storage_exception(
    _request: Request, exc: ClientError | BotoCoreError
) -> JSONResponse:
    api_code = _classify_storage_exception(exc)

    operation_name: str | None = None
    error_code: str | None = None
    upstream_status: int | None = None
    request_id: str | None = None
    if isinstance(exc, ClientError):
        operation_name = exc.operation_name
        response = exc.response
        raw_error_code = (response.get("Error") or {}).get("Code")
        error_code = str(raw_error_code) if raw_error_code is not None else None
        metadata = response.get("ResponseMetadata") or {}
        raw_status = metadata.get("HTTPStatusCode")
        upstream_status = raw_status if isinstance(raw_status, int) else None
        raw_request_id = metadata.get("RequestId")
        request_id = str(raw_request_id) if raw_request_id is not None else None

    logger.error(
        "Storage operation failed: api_code=%s exc_type=%s operation=%s "
        "error_code=%s upstream_status=%s request_id=%s",
        api_code.code,
        type(exc).__name__,
        operation_name,
        error_code,
        upstream_status,
        request_id,
        exc_info=exc,
    )
    return _error_response(api_code)


async def handle_unexpected_exception(
    _request: Request, _exc: Exception
) -> JSONResponse:
    return _error_response(CommonApiCode.INTERNAL_ERROR)
