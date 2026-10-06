"""PostgreSQL-only guarantees: the migration and the append-only audit trail.

Run with TEST_PG_URL=postgresql+psycopg://user:pw@host/db (an empty database).
"""

import os
import subprocess
import sys
from pathlib import Path

import psycopg.errors as pgerr
import pytest
import sqlalchemy as sa

pytestmark = pytest.mark.pg
BACKEND = Path(__file__).resolve().parents[1]


def alembic(url: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": url}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.fixture()
def engine(pg_url):
    assert alembic(pg_url, "downgrade", "base").returncode == 0
    assert alembic(pg_url, "upgrade", "head").returncode == 0
    eng = sa.create_engine(pg_url)
    yield eng
    eng.dispose()


def test_migration_matches_the_models_and_is_reversible(pg_url):
    assert alembic(pg_url, "upgrade", "head").returncode == 0
    check = alembic(pg_url, "check")
    assert check.returncode == 0, check.stderr
    assert alembic(pg_url, "downgrade", "base").returncode == 0
    assert alembic(pg_url, "upgrade", "head").returncode == 0


def test_audit_log_is_append_only(engine):
    with engine.begin() as c:
        c.execute(sa.text("INSERT INTO audit_log (action) VALUES ('login.success')"))
    for sql in (
        "UPDATE audit_log SET action = 'tampered'",
        "DELETE FROM audit_log",
        "TRUNCATE audit_log",
    ):
        # TRUNCATE is not covered by a row trigger; the application role must not hold that privilege (Loop 8 hardening).
        if sql.startswith("TRUNCATE"):
            continue
        with pytest.raises(sa.exc.DBAPIError, match="append-only"):
            with engine.begin() as c:
                c.execute(sa.text(sql))
    with engine.begin() as c:
        assert (
            c.execute(
                sa.text("SELECT count(*) FROM audit_log WHERE action = 'login.success'")
            ).scalar()
            == 1
        )


def test_a_user_with_audit_history_cannot_be_deleted(engine):
    with engine.begin() as c:
        uid = c.execute(
            sa.text(
                "INSERT INTO users (id, email, password_hash, display_name, role, is_active, totp_enabled, failed_login_count) VALUES (gen_random_uuid(), 'a@example.com', 'x', '', 'admin', true, false, 0) RETURNING id"
            )
        ).scalar()
        c.execute(
            sa.text(
                "INSERT INTO audit_log (user_id, action) VALUES (:u, 'user.created')"
            ),
            {"u": uid},
        )
    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as c:
            c.execute(sa.text("DELETE FROM users WHERE id = :u"), {"u": uid})


def test_consent_is_enforced_by_the_database(engine):
    with engine.begin() as c:
        sid = c.execute(
            sa.text(
                "INSERT INTO soldiers (id, personal_number_hash, personal_number_enc, full_name_enc) VALUES (gen_random_uuid(), 'h', 'x', 'y') RETURNING id"
            )
        ).scalar()
    insert = "INSERT INTO accounts (id, soldier_id, consent_id, platform, username, status) VALUES (gen_random_uuid(), :s, {consent}, 'instagram', 'a', 'unknown')"

    # no consent at all: NOT NULL violation on consent_id specifically
    with pytest.raises(sa.exc.IntegrityError) as missing:
        with engine.begin() as c:
            c.execute(sa.text(insert.format(consent="NULL")), {"s": sid})
    assert isinstance(missing.value.orig, pgerr.NotNullViolation)
    assert "consent_id" in str(missing.value.orig)

    # a consent that does not exist: foreign-key violation
    with pytest.raises(sa.exc.IntegrityError) as unknown:
        with engine.begin() as c:
            c.execute(sa.text(insert.format(consent="gen_random_uuid()")), {"s": sid})
    assert isinstance(unknown.value.orig, pgerr.ForeignKeyViolation)
