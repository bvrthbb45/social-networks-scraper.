"""Engine, session factory and the declarative base (naming conventions keep migrations stable)."""

from collections.abc import Iterator

from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "ix": "ix_%(column_0_label)s",
}
NAMING_CONVENTION = _CONVENTION  # public alias used by tests/migrations


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=_CONVENTION)


engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Iterator[Session]:
    """One session per request, always closed."""
    with SessionLocal() as session:
        yield session
