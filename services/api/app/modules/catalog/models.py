from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ...database import Base


class CatalogShare(Base):
    """The tenant's public catalog link.

    One row per tenant. ``token`` is the whole credential — the public page has
    no session — so it is 32 random URL-safe characters, unique, and revoked by
    deleting the row. Separate from ``users`` on purpose: the catalog does not
    depend on the auth model, and a team member's account row is not the tenant.
    """

    __tablename__ = "catalog_shares"
    __table_args__ = (
        # The public lookup is by token alone; uniqueness is what makes it a
        # single link rather than a shared namespace.
        Index("uq_catalog_shares_token", "token", unique=True),
    )

    tenant_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    token: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class CatalogItem(Base):
    """One sellable item: the assistant's only source for price and stock.

    The catalog is intentionally small and human-maintained. The prompt block
    quotes these rows verbatim, so a wrong row is a wrong answer the customer
    acts on — the CRUD surface is the guard, not model judgement.
    """

    __tablename__ = "catalog_items"
    __table_args__ = (
        # The prompt lookup is always "active items for this tenant, in display
        # order"; the SKU index backs the admin search.
        Index("ix_catalog_items_tenant_active", "tenant_id", "active", "sort_order"),
        Index("ix_catalog_items_tenant_sku", "tenant_id", "sku"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sku: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # Numeric, not float: 0.1 + 0.2 money errors are not acceptable in a quote.
    price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    # NULL rather than a guessed default: printing the wrong currency is worse
    # than printing a bare amount.
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    item_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    in_stock: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    # "ships in 2 days", "back in stock Monday" — shown next to availability.
    availability_note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
