import logging
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import cast

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


async def handle_unexpected_exception(
    _request: Request, _exc: Exception
) -> JSONResponse:
    return _error_response(CommonApiCode.INTERNAL_ERROR)
