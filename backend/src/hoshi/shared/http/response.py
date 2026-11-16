from typing import Self

from pydantic import BaseModel, Field

from hoshi.shared.http.api_code import ApiCode, CommonApiCode


class FieldError(BaseModel):
    field: str
    message: str


class ApiResponse[T](BaseModel):
    data: T
    code: str
    message: str
    errors: list[FieldError] = Field(default_factory=list)

    @classmethod
    def success(cls, data: T) -> Self:
        return cls(
            data=data,
            code=CommonApiCode.SUCCESS.code,
            message=CommonApiCode.SUCCESS.message,
        )

    @classmethod
    def error(
        cls,
        api_code: ApiCode,
        message: str | None = None,
        *,
        errors: list[FieldError] | None = None,
    ) -> Self:
        return cls(
            data=None,
            code=api_code.code,
            message=api_code.message if message is None else message,
            errors=errors if errors is not None else [],
        )
