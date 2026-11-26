from collections.abc import AsyncIterator
from typing import Annotated, cast

from fastapi import Depends, Query, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hoshi.core.config import Settings
from hoshi.core.security import get_password_encoder
from hoshi.infra.object_storage import S3ObjectStorage
from hoshi.modules.auth.service import AccountAuthenticator
from hoshi.modules.user.repository import UserRepository
from hoshi.modules.user.service import AccountAuthenticateService
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


type RedisDependency = Annotated[Redis, Depends(get_redis)]


def get_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


type SettingsDependency = Annotated[Settings, Depends(get_settings)]


def get_account_authenticator(session: SessionDependency) -> AccountAuthenticator:
    return AccountAuthenticateService(
        session, get_password_encoder(), UserRepository(session)
    )


async def get_object_storage(request: Request) -> S3ObjectStorage:
    return cast(S3ObjectStorage, request.app.state.object_storage)


type ObjectStorageDependency = Annotated[S3ObjectStorage, Depends(get_object_storage)]
