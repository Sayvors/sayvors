"""Platform admin operator accounts and audit log.

Replaces the single shared admin password with named operator accounts, each
with its own bcrypt-hashed password, role, and active flag. Every mutation
against /api/v1/admin/* is recorded in admin_audit_logs for accountability.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ...database import Base


class PlatformOperator(Base):
    __tablename__ = "platform_operators"
    __table_args__ = (
        # The migrated table has a UNIQUE constraint on username
        # (platform_operators_username_key) plus this plain index. Declaring
        # both keeps a models-only rebuild identical to the migration chain.
        Index("ix_platform_operators_username", "username"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default="operator", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PurgedAccount(Base):
    """Trace of an account the platform removed without the owner asking.

    Unverified accounts are deleted after a grace period so they cannot
    accumulate or be mailed. The row keeps the address, signup time and a small
    metadata snapshot for support/audit; it is not a user and never receives
    email. `tenant_id` columns deliberately do not exist so a tenant purge
    cannot delete this table (it is also in admin.tenant_ops._SYSTEM_TABLES).
    """

    __tablename__ = "purged_accounts"
    __table_args__ = (
        Index("ix_purged_accounts_email", "email"),
        Index("ix_purged_accounts_purged_at", "purged_at"),
    )

    # The original users.id. A new signup gets a new id, so this stays unique.
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(320))
    first_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reason: Mapped[str] = mapped_column(String(32), default="unverified")
    # pending | purged | failed
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    signed_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    purged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    metadata_json: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=sa_text("'{}'")
    )


class AdminNotification(Base):
    """In-app notification for platform operators.

    `operator_id` NULL = broadcast (visible to every admin). Kinds:
    request (billing/plan), error (delivery/system), finance, system.
    """

    __tablename__ = "admin_notifications"
    __table_args__ = (
        Index("ix_admin_notifications_operator_read_created", "operator_id", "read_at", "created_at"),
        Index("ix_admin_notifications_created", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    operator_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("platform_operators.id", ondelete="CASCADE"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(24), default="system", index=True)
    severity: Mapped[str] = mapped_column(String(12), default="info")
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    href: Mapped[str | None] = mapped_column(String(300), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    operator_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("platform_operators.id", ondelete="SET NULL"), nullable=True, index=True
    )
    operator_username: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    method: Mapped[str] = mapped_column(String(10))
    path: Mapped[str] = mapped_column(String(256))
    status_code: Mapped[int] = mapped_column(Integer, default=0)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(256), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )