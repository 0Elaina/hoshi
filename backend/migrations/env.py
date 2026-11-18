from logging.config import fileConfig

from alembic import context
from sqlalchemy import URL, create_engine
from sqlalchemy.pool import NullPool

from hoshi.core.config import Settings
from hoshi.db.base import Base
from hoshi.modules.auth.models import AuthSession  # noqa: F401
from hoshi.modules.user.models import UserAccount  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline(url: URL) -> None:
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online(url: URL) -> None:
    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


database_url = Settings().database_url()  # pyright: ignore
if context.is_offline_mode():
    run_migrations_offline(database_url)
else:
    run_migrations_online(database_url)
