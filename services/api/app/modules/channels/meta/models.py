"""Meta integration models (WhatsApp / Facebook / Instagram).

Generic multi-tenant connection layer. Every row belongs to a Sayvors tenant
(`tenant_id` == users.id); every query must filter by it. Per-tenant Meta
credentials are Fernet-encrypted at rest (see credentials.py).
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ....database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MetaConnection(Base):
    """One (tenant, provider) connection: token + health."""

    __tablename__ = "meta_connections"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", name="uq_meta_connections_tenant_provider"),
        Index("ix_meta_connections_tenant", "tenant_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    provider: Mapped[str] = mapped_column(
        Enum("whatsapp", "facebook", "instagram", name="meta_provider"),
        index=True,
    )
    connection_type: Mapped[str] = mapped_column(String(50), default="oauth")
    meta_business_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    access_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(
        Enum("active", "needs_reauth", "expired", "revoked", "error", name="meta_connection_status"),
        default="active",
        index=True,
    )
    connection_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_successful_api_call_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_webhook_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    assets: Mapped[list["MetaAsset"]] = relationship(
        "MetaAsset", back_populates="connection", cascade="all, delete-orphan"
    )


class MetaAsset(Base):
    """One provider asset (WABA, phone number, Page, IG account)."""

    __tablename__ = "meta_assets"
    __table_args__ = (
        UniqueConstraint("provider", "external_asset_id", name="uq_meta_assets_provider_external"),
        Index("ix_meta_assets_tenant", "tenant_id"),
        Index("ix_meta_assets_connection", "connection_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    connection_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meta_connections.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(
        Enum("whatsapp", "facebook", "instagram", name="meta_provider"),
        index=True,
    )
    asset_type: Mapped[str] = mapped_column(
        Enum("waba", "phone_number", "page", "ig_account", name="meta_asset_type"),
        index=True,
    )
    external_asset_id: Mapped[str] = mapped_column(String(100), index=True)
    parent_asset_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("meta_assets.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(50), default="connected")
    asset_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    connection: Mapped["MetaConnection"] = relationship("MetaConnection", back_populates="assets")


class MetaOAuthTransaction(Base):
    """Server-side OAuth transaction: state hash, tenant binding, one-time use."""

    __tablename__ = "meta_oauth_transactions"
    __table_args__ = (Index("ix_meta_oauth_tenant", "tenant_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    provider: Mapped[str] = mapped_column(
        Enum("whatsapp", "facebook", "instagram", name="meta_provider"),
        index=True,
    )
    state_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(
        Enum("pending", "completed", "failed", "expired", name="meta_oauth_status"),
        default="pending",
        index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    transaction_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class MetaWebhookEvent(Base):
    """Raw Meta webhook payload retention + idempotency ledger."""

    __tablename__ = "meta_webhook_events"
    __table_args__ = (
        UniqueConstraint(
            "provider", "external_event_id", "event_type",
            name="uq_meta_webhook_events_dedupe",
        ),
        Index("ix_meta_webhook_tenant", "tenant_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    provider: Mapped[str] = mapped_column(
        Enum("whatsapp", "facebook", "instagram", "unknown", name="meta_webhook_provider"),
        index=True,
    )
    external_event_id: Mapped[str] = mapped_column(String(255), index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    connection_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(
        Enum("received", "processed", "duplicate", "rejected", "unresolved",
             name="meta_webhook_status"),
        default="received",
        index=True,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
