import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ...database import Base


class TeamRole(Base):
    """A tenant-scoped role: a named set of permission strings.
    `is_system` rows are the seeded templates (read-only); tenants create
    custom (dynamic) roles as normal rows. The workspace owner is implicit
    and has every permission without a row."""

    __tablename__ = "team_roles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_team_roles_tenant_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(100))
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    permissions: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class TeamMember(Base):
    """One invited person per workspace. `user_id` stays NULL until the
    invite is accepted (matched by email at signup/login). Phase 1: a user
    belongs to exactly one workspace — enforced by the unique user_id —
    set to their tenant_id at accept time. The invite token follows the
    password-reset pattern: only the SHA-256 hash is stored."""

    __tablename__ = "team_members"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_team_members_tenant_email"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, unique=True, index=True
    )
    email: Mapped[str] = mapped_column(String(255), index=True)
    role_id: Mapped[str] = mapped_column(String(36), ForeignKey("team_roles.id", ondelete="RESTRICT"), index=True)
    status: Mapped[str] = mapped_column(
        Enum("invited", "active", "suspended", name="team_member_status"),
        default="invited",
    )
    invited_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    invite_token_hash: Mapped[str | None] = mapped_column(String(128), unique=True, index=True, nullable=True)
    invite_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TeamMemberChannel(Base):
    """Per-channel access override for one member. Effective level for a
    channel = this row if present, else the member's role default
    (channels.view / channels.edit / none)."""

    __tablename__ = "team_member_channels"
    __table_args__ = (
        UniqueConstraint("member_id", "channel_id", name="uq_team_member_channels_member_channel"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    member_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("team_members.id", ondelete="CASCADE"), index=True
    )
    channel_id: Mapped[str] = mapped_column(String(36), index=True)
    level: Mapped[str] = mapped_column(Enum("none", "view", "edit", name="team_channel_level"))
