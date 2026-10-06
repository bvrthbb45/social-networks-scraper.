"""Database schema.

Principles
- Collection is restricted by design: an ``Account`` cannot exist without a ``Consent``
  (NOT NULL foreign key), and ``Post`` rows only ever belong to an account.
- Personal and sensitive values are stored encrypted. Columns ending in ``_enc`` hold
  AES-256-GCM ciphertext (implemented in Loop 2); ``*_hash`` columns are HMAC blind
  indexes so records can be looked up without decrypting.
- Every collected item carries ``delete_after``: retention is enforced by a purge job.
- The audit log is append-only (a database trigger rejects UPDATE and DELETE).
- Enumerations are strings guarded by CHECK constraints (easy to migrate).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

# JSONB on PostgreSQL, generic JSON elsewhere (tests).
JsonType = JSON().with_variant(JSONB(), "postgresql")

ROLES = ("uploader", "reviewer", "admin", "auditor")
PLATFORMS = (
    "instagram",
    "tiktok",
    "facebook",
)  # WhatsApp has no public content: not supported
ACCOUNT_STATUSES = ("open", "closed", "unknown", "not_found")
CONSENT_STATUSES = ("active", "revoked", "expired")
FINDING_KINDS = (
    "uniform",
    "equipment",
    "classified_document",
    "screen_photo",
    "codename",
    "location",
    "text_pattern",
)
SEVERITIES = ("low", "medium", "high")
FINDING_STATUSES = ("new", "in_review", "confirmed", "dismissed", "escalated")
DECISIONS = ("confirmed", "dismissed", "escalated")
TERM_KINDS = ("codename", "site", "unit", "other")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=uuid.uuid4)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


# --------------------------------------------------------------------------- #
# Operators (people who use the system) and the audit trail
# --------------------------------------------------------------------------- #


class User(Base):
    """A security-department operator. Separation of duties is by ``role``:
    uploader (imports files), reviewer (decides on findings), admin (manages
    users and watch-lists), auditor (read-only access to the audit trail)."""

    __tablename__ = "users"
    __table_args__ = (CheckConstraint(_in("role", ROLES), name="role"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))  # Argon2id
    display_name: Mapped[str] = mapped_column(String(120), default="")
    role: Mapped[str] = mapped_column(String(10))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    totp_secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_last_step: Mapped[int | None] = mapped_column(BigInteger)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = _created()


class AuditLog(Base):
    """Who did what. Append-only; never store personal data or secrets in ``details``."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    # RESTRICT: a user with audit history can never be deleted (deactivate instead), because
    # rewriting audit rows is forbidden by the append-only trigger.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    action: Mapped[str] = mapped_column(String(80), index=True)
    object_type: Mapped[str | None] = mapped_column(String(40))
    object_id: Mapped[str | None] = mapped_column(String(64))
    ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    details: Mapped[dict | None] = mapped_column(JsonType)
    created_at: Mapped[datetime] = _created()


# --------------------------------------------------------------------------- #
# Roster and consent
# --------------------------------------------------------------------------- #


class Soldier(Base):
    __tablename__ = "soldiers"

    id: Mapped[uuid.UUID] = _uuid_pk()
    # Personal number, HMAC blind index only: lets the importer match a row without storing it in the clear.
    personal_number_hash: Mapped[str] = mapped_column(String(64), unique=True)
    personal_number_enc: Mapped[bytes] = mapped_column(LargeBinary)
    full_name_enc: Mapped[bytes] = mapped_column(LargeBinary)
    unit_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = _created()

    # passive_deletes: the database cascades; the ORM must not null the foreign keys first.
    consents: Mapped[list["Consent"]] = relationship(
        back_populates="soldier", passive_deletes=True
    )


class Consent(Base):
    """The signed consent. Monitoring is permitted only while a consent is active and in date."""

    __tablename__ = "consents"
    __table_args__ = (
        CheckConstraint(_in("status", CONSENT_STATUSES), name="status"),
        CheckConstraint("valid_until >= valid_from", name="validity_order"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    soldier_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("soldiers.id", ondelete="CASCADE"), index=True
    )
    document_ref: Mapped[str] = mapped_column(
        String(120)
    )  # reference to the signed form (not the form)
    signed_on: Mapped[date] = mapped_column(Date)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_until: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10), default="active", index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()

    soldier: Mapped[Soldier] = relationship(back_populates="consents")


class Import(Base):
    """One uploaded Excel file. Rejection reasons are aggregated counts, never row contents."""

    __tablename__ = "imports"
    __table_args__ = (
        CheckConstraint(_in("status", ("processing", "done", "failed")), name="status"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(12), default="processing")
    rows_total: Mapped[int] = mapped_column(Integer, default=0)
    rows_accepted: Mapped[int] = mapped_column(Integer, default=0)
    rows_rejected: Mapped[int] = mapped_column(Integer, default=0)
    reject_reasons: Mapped[dict | None] = mapped_column(JsonType)
    uploaded_at: Mapped[datetime] = _created()


# --------------------------------------------------------------------------- #
# Accounts and collected public content
# --------------------------------------------------------------------------- #


class Account(Base):
    """A social account. ``consent_id`` is NOT NULL: no consent, no account."""

    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("platform", "username", name="platform_username"),
        CheckConstraint(_in("platform", PLATFORMS), name="platform"),
        CheckConstraint(_in("status", ACCOUNT_STATUSES), name="status"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    soldier_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("soldiers.id", ondelete="CASCADE"), index=True
    )
    consent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("consents.id", ondelete="CASCADE"), index=True
    )
    platform: Mapped[str] = mapped_column(String(10))
    username: Mapped[str] = mapped_column(
        String(100)
    )  # normalised (lower case, no "@")
    status: Mapped[str] = mapped_column(String(10), default="unknown")
    status_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_import_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("imports.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()

    posts: Mapped[list["Post"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )


class Post(Base):
    """Public content collected from an open account. Deleted automatically at ``delete_after``."""

    __tablename__ = "posts"
    __table_args__ = (
        UniqueConstraint("account_id", "content_hash", name="account_content"),
        CheckConstraint(
            "delete_after > collected_at", name="retention_after_collection"
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    external_id: Mapped[str | None] = mapped_column(String(120))
    url: Mapped[str | None] = mapped_column(String(500))
    posted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    text_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    media: Mapped[list | None] = mapped_column(
        JsonType
    )  # [{"kind": "image", "ref": "<hash>"}], files live outside the DB
    content_hash: Mapped[str] = mapped_column(String(64))  # idempotent import
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    delete_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    account: Mapped[Account] = relationship(back_populates="posts")
    findings: Mapped[list["Finding"]] = relationship(
        back_populates="post", cascade="all, delete-orphan"
    )


# --------------------------------------------------------------------------- #
# Detection
# --------------------------------------------------------------------------- #


class WatchlistTerm(Base):
    """A code name / site / unit to detect. Encrypted: the list itself is sensitive."""

    __tablename__ = "watchlist_terms"
    __table_args__ = (
        CheckConstraint(_in("kind", TERM_KINDS), name="kind"),
        CheckConstraint(_in("severity", SEVERITIES), name="severity"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    term_hash: Mapped[str] = mapped_column(
        String(64), unique=True
    )  # blind index of the normalised term
    term_enc: Mapped[bytes] = mapped_column(LargeBinary)
    aliases_enc: Mapped[bytes | None] = mapped_column(
        LargeBinary
    )  # encrypted JSON list
    kind: Mapped[str] = mapped_column(String(10), default="codename")
    severity: Mapped[str] = mapped_column(String(10), default="medium")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()


class Finding(Base):
    """An automated indication. It is only a lead: a person decides (see ``Review``)."""

    __tablename__ = "findings"
    __table_args__ = (
        UniqueConstraint("post_id", "kind", "evidence_hash", name="post_kind_evidence"),
        CheckConstraint(_in("kind", FINDING_KINDS), name="kind"),
        CheckConstraint(_in("severity", SEVERITIES), name="severity"),
        CheckConstraint(_in("status", FINDING_STATUSES), name="status"),
        CheckConstraint("score >= 0 AND score <= 1", name="score_range"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20))
    score: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    severity: Mapped[str] = mapped_column(String(10), index=True)
    reason_enc: Mapped[bytes] = mapped_column(
        LargeBinary
    )  # human-readable Hebrew explanation
    evidence_enc: Mapped[bytes | None] = mapped_column(
        LargeBinary
    )  # matched text / image regions
    evidence_hash: Mapped[str] = mapped_column(String(64))  # idempotent analysis
    engine_version: Mapped[str] = mapped_column(String(40), default="")
    status: Mapped[str] = mapped_column(String(10), default="new", index=True)
    created_at: Mapped[datetime] = _created()

    post: Mapped[Post] = relationship(back_populates="findings")
    reviews: Mapped[list["Review"]] = relationship(
        back_populates="finding", cascade="all, delete-orphan"
    )


class Review(Base):
    """A reviewer's decision on a finding."""

    __tablename__ = "reviews"
    __table_args__ = (CheckConstraint(_in("decision", DECISIONS), name="decision"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    finding_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("findings.id", ondelete="CASCADE"), index=True
    )
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    decision: Mapped[str] = mapped_column(String(10))
    note_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    decided_at: Mapped[datetime] = _created()

    finding: Mapped[Finding] = relationship(back_populates="reviews")
