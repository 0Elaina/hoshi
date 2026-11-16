from typing import Annotated, TypeVar

from fastapi import Query
from fastapi_pagination import Page, Params
from fastapi_pagination.customization import (
    CustomizedPage,
    UseExcludedFields,
    UseFieldsAliases,
    UseName,
)
from pydantic import BeforeValidator


def _validate_integer_query_value(value: object) -> object:
    if isinstance(value, str) and not value.strip().isdecimal():
        raise ValueError("必须是整数")
    return value


PageInteger = Annotated[int, BeforeValidator(_validate_integer_query_value)]
ItemT = TypeVar("ItemT")


class PageQuery(Params):
    page: PageInteger = Query(default=1, ge=1)
    size: PageInteger = Query(default=20, ge=1, le=100, alias="pageSize")


PageResult = CustomizedPage[
    Page[ItemT],
    UseFieldsAliases(size="pageSize"),
    UseExcludedFields("pages"),
    UseName("PageResult"),
]
PageQuery.set_page(PageResult)
