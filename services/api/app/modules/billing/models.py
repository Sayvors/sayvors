"""Billing profiles + saved payment methods (card-on-file records).

PCI scope note: raw card numbers (PANs) and CVCs are NEVER accepted,
stored, or logged anywhere in this module. Cards are stored as
brand/last4/expiry metadata; live charging/verification happens through
a payment gateway later (see providers.py). Until a gateway is wired,
rows are `verified=False` records the merchant maintains.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ...database import Base


class BillingProfile(Base):
    """One billing identity per tenant (details for invoices/receipts)."""

    __tablename__ = "billing_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    full_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address_line1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    region: Mapped[str | None] = mapped_column(String(120), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    country: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # VAT / tax registration number (e.g. Saudi ZATCA VAT number).
    tax_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class PaymentMethod(Base):
    """A saved card record. Metadata only — never a PAN or CVC."""

    __tablename__ = "payment_methods"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    brand: Mapped[str] = mapped_column(String(20), default="card")
    last4: Mapped[str] = mapped_column(String(4))
    exp_month: Mapped[int] = mapped_column(Integer)
    exp_year: Mapped[int] = mapped_column(Integer)
    holder_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    # Gateway that verified/charges this card. "manual" until a gateway
    # is wired (see providers.py); gateway ids accepted only when their
    # provider is configured.
    provider: Mapped[str] = mapped_column(String(30), default="manual")
    provider_payment_method_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # True once a gateway confirms the card. Manual records stay False.
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class BillingEvent(Base):
    """Durable credit ledger: grants, holds, charges, refunds, and baselines.

    One ``ai_usage`` row per LLM call. It is inserted as ``pending`` when the
    wallet is reserved and finalized exactly once by ``settle`` (``settled``
    or ``released``). Grants/top-ups use ``posted`` and carry the full amount.

    ``balance_resync`` is a one-time opening baseline for a tenant that
    predates the ledger. ``balance_reconcile`` is a zero-amount audit row
    written when an operator repairs a drifted Redis cache. Neither is counted
    as new credit.

    The row is the idempotency boundary: settle changes this row, never
    inserts a second charge for the same reservation.
    """

    __tablename__ = "billing_events"
    __table_args__ = (
        # Partial unique index: a NULL key means "never dedupe", so the index
        # only covers rows that actually carry a key. Same object the
        # migration creates; PostgreSQL-only WHERE is ignored on SQLite,
        # where a full unique index has identical NULL semantics.
        Index(
            "uq_billing_events_tenant_idempotency",
            "tenant_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        Index("ix_billing_events_status_expires", "status", "expires_at"),
        Index("ix_billing_events_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    # posted | pending | settled | released | expired
    status: Mapped[str] = mapped_column(String(16), default="posted")
    amount_cents: Mapped[int] = mapped_column(Integer, default=0)
    reserved_cents: Mapped[int] = mapped_column(Integer, default=0)
    balance_after_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
