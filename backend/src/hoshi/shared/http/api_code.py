from dataclasses import dataclass

from fastapi import status


@dataclass(frozen=True)
class ApiCode:
    http_status: int
    code: str
    message: str


class CommonApiCode:
    SUCCESS = ApiCode(status.HTTP_200_OK, "SUCCESS", "响应成功")
    INVALID_ARGUMENT = ApiCode(
        status.HTTP_400_BAD_REQUEST, "INVALID_ARGUMENT", "请求参数无效"
    )
    ROUTE_NOT_FOUND = ApiCode(
        status.HTTP_404_NOT_FOUND, "ROUTE_NOT_FOUND", "请求路径不存在"
    )
    METHOD_NOT_ALLOWED = ApiCode(
        status.HTTP_405_METHOD_NOT_ALLOWED, "METHOD_NOT_ALLOWED", "请求方法不受支持"
    )
    INTERNAL_ERROR = ApiCode(
        status.HTTP_500_INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "服务器内部错误"
    )
