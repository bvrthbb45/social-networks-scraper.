import base64
import os

os.environ.setdefault("ENVIRONMENT", "test")

import pytest  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.database import Base  # noqa: E402
from app import models  # noqa: E402,F401

KEY = base64.b64encode(b"k" * 32).decode()
KEY2 = base64.b64encode(b"m" * 32).decode()


@pytest.fixture()
def db():
    """In-memory SQLite with foreign keys ENFORCED (off by default in SQLite)."""
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _fk_on(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False)() as session:
        yield session


@pytest.fixture()
def pg_url():
    url = os.environ.get("TEST_PG_URL")
    if not url:
        pytest.skip("TEST_PG_URL not set")
    return url
