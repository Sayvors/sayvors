"""PostgreSQL-backed WhatsApp usage reservations and Meta spend facts."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    BigInteger, CheckConstraint, Date, DateTime, Index,
    Integer, Numeric, String, UniqueConstraint, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ....database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WhatsAppSpendDaily(Base):
    """One approximate Meta fact per WABA/date/full pricing dimension tuple."""

    __tablename__ = "whatsapp_spend_daily"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "waba_id", "spend_date", "attribution_hash",
            name="uq_whatsapp_spend_daily_attribution",
        ),
        Index("ix_whatsapp_spend_daily_tenant_date", "tenant_id", "spend_date"),
        Index("ix_whatsapp_spend_daily_waba_date", "waba_id", "spend_date"),
        Index(
            "ix_whatsapp_spend_daily_funding_date",
            "funding_mode", "spend_date",
        ),
        CheckConstraint("volume >= 0", name="ck_whatsapp_spend_daily_volume"),
        CheckConstraint(
            "cost IS NULL OR cost >= 0",
            name="ck_whatsapp_spend_daily_cost",
        ),
        CheckConstraint(
            "cost_status IN ('available', 'unavailable')",
            name="ck_whatsapp_spend_daily_cost_status",
        ),
        CheckConstraint(
            "funding_mode IN ('direct_client', 'shared_credit_line', "
            "'platform_liable', 'unknown')",
            name="ck_whatsapp_spend_daily_funding_mode",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    waba_id: Mapped[str] = mapped_column(String(100), nullable=False)
    messaging_account_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    spend_date: Mapped[date] = mapped_column(Date, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    country: Mapped[str | None] = mapped_column(String(8), nullable=True)
    pricing_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    pricing_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tier: Mapped[str | None] = mapped_column(String(50), nullable=True)
    attribution_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0", nullable=False)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    cost_status: Mapped[str] = mapped_column(String(20), default="unavailable", nullable=False)
    funding_mode: Mapped[str] = mapped_column(String(40), default="unknown", nullable=False)
    waba_timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(30), default="pricing_analytics", nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class WhatsAppQuotaReservation(Base):
    """Durable idempotency and settlement record for one Messages API attempt."""

    __tablename__ = "whatsapp_quota_reservations"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "idempotency_key",
            name="uq_whatsapp_quota_reservations_tenant_key",
        ),
        Index(
            "ix_whatsapp_quota_reservations_tenant_month",
            "tenant_id", "month",
        ),
        Index(
            "ix_whatsapp_quota_reservations_provider_message",
            "provider_message_id",
            postgresql_where=text("provider_message_id IS NOT NULL"),
        ),
        CheckConstraint(
            "status IN ('reserved', 'consumed', 'released')",
            name="ck_whatsapp_quota_reservations_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), default="whatsapp", server_default="whatsapp", nullable=False)
    month: Mapped[date] = mapped_column(Date, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="reserved", server_default="reserved", nullable=False)
    phone_number_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    failure_classification: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WhatsAppMonthlyUsage(Base):
    """Atomic tenant/month counter; the row lock serializes quota decisions."""

    __tablename__ = "whatsapp_monthly_usage"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "month", name="uq_whatsapp_monthly_usage_tenant_month"
        ),
        CheckConstraint("used_count >= 0", name="ck_whatsapp_monthly_usage_used"),
    )

    tenant_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    month: Mapped[date] = mapped_column(Date, primary_key=True)
    used_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
