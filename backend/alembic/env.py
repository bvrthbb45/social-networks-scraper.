"""Alembic runtime: migrations run against the application's own settings and metadata."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from app import models  # noqa: F401  (importing registers every table on Base.metadata)
from app.config import settings
from app.database import Base

if context.config.config_file_name:
    fileConfig(context.config.config_file_name)


def _run(**connection_args) -> None:
    context.configure(
        target_metadata=Base.metadata, compare_type=True, **connection_args
    )
    with context.begin_transaction():
        context.run_migrations()


def migrate_offline() -> None:
    _run(url=settings.database_url, literal_binds=True)


def migrate_online() -> None:
    with create_engine(settings.database_url).connect() as connection:
        _run(connection=connection)


(migrate_offline if context.is_offline_mode() else migrate_online)()
