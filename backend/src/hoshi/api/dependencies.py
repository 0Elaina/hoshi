from collections.abc import AsyncIterator
from typing import Annotated, cast

from fastapi import Depends, Query, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hoshi.shared.http.pagination import PageQuery

type PageParams = Annotated[PageQuery, Query()]


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory = cast(
        async_sessionmaker[AsyncSession], request.app.state.session_factory
    )
    async with session_factory() as session:
        yield session


type SessionDependency = Annotated[AsyncSession, Depends(get_session)]


async def get_redis(request: Request) -> Redis:
    return cast(Redis, request.app.state.redis)
