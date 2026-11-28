from collections.abc import AsyncIterator
from typing import Annotated, cast

from fastapi import Depends, Query, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hoshi.core.config import Settings
from hoshi.core.security import get_password_encoder
from hoshi.modules.auth.service import AccountAuthenticator
from hoshi.modules.files.storage import FileObjectStorage
from hoshi.modules.user.repository import UserRepository
from hoshi.modules.user.service import AccountAuthenticateService
from hoshi.shared.http.api_code import CommonApiCode
from hoshi.shared.http.exception import BusinessException
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


def get_file_storage(request: Request) -> FileObjectStorage:
    storage = cast(FileObjectStorage | None, request.app.state.file_storage)
    if storage is None:
        raise BusinessException(CommonApiCode.STORAGE_UNAVAILABLE)
    return storage


type FileStorageDependency = Annotated[FileObjectStorage, Depends(get_file_storage)]


def get_account_authenticator(session: SessionDependency) -> AccountAuthenticator:
    return AccountAuthenticateService(
        session, get_password_encoder(), UserRepository(session)
    )
