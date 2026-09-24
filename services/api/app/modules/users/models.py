import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ...database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    business_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Business context for AI grounding (tenant-owned identity):
    # what the company sells, explicitly does NOT sell, and a 1-line summary.
    business_sells: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_doesnt_sell: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    referral: Mapped[str | None] = mapped_column(String(100), nullable=True)
    newsletter: Mapped[bool] = mapped_column(Boolean, default=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    onboarded: Mapped[bool] = mapped_column(Boolean, default=False)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    theme: Mapped[str] = mapped_column(String(20), default="light")
    language: Mapped[str] = mapped_column(String(10), default="en")
    # Google identity (sign-in with Google). Non-NULL google_sub ⇒ the account
    # authenticates via Google; password_hash stays a random unusable value.
    google_sub: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Facebook identity (Continue with Facebook). Mirrors google_sub.
    facebook_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    # Account-wide country (ISO code) — display/defaults only, never listings.
    country: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # Plan + AI credit balance (P0 billing gate): plan ∈ {free, pro};
    # ai_credit_cents is a USD-cent balance spent by every AI task.
    plan: Mapped[str] = mapped_column(String(16), default="free")
    ai_credit_cents: Mapped[int] = mapped_column(Integer, default=0)
    # Access-token generation: bumped on password change / logout-all so
    # previously issued access tokens are rejected (G1 revocation).
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
