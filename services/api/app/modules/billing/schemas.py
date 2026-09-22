from pydantic import BaseModel, Field


class BillingProfileIn(BaseModel):
    full_name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    address_line1: str | None = Field(default=None, max_length=255)
    address_line2: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=120)
    region: str | None = Field(default=None, max_length=120)
    postal_code: str | None = Field(default=None, max_length=20)
    country: str | None = Field(default=None, max_length=8)
    tax_id: str | None = Field(default=None, max_length=50)


class BillingProfileOut(BillingProfileIn):
    id: str
    user_id: str


class PaymentMethodIn(BaseModel):
    brand: str = Field(..., min_length=1, max_length=20,
                       description="Card brand: visa, mastercard, mada, amex, ...")
    last4: str = Field(..., min_length=4, max_length=4, pattern=r"^[0-9]{4}$")
    exp_month: int = Field(..., ge=1, le=12)
    exp_year: int = Field(..., ge=2000, le=2100)
    holder_name: str | None = Field(default=None, max_length=200)
    is_default: bool = False
    # Gateway provider id. "manual" = unverified local record; "stub" =
    # local stub gateway (tokenized, verified). Anything else 422s until
    # real keys are configured (see providers.py).
    provider: str = Field(default="manual", max_length=30)
    # Opaque token from POST /billing/gateway/tokenize (stub: pm_stub_*).
    provider_token: str | None = Field(default=None, max_length=255)


class GatewayTokenizeIn(BaseModel):
    brand: str = Field(..., min_length=1, max_length=20)
    last4: str = Field(..., min_length=4, max_length=4, pattern=r"^[0-9]{4}$")
    exp_month: int = Field(..., ge=1, le=12)
    exp_year: int = Field(..., ge=2000, le=2100)
    holder_name: str | None = Field(default=None, max_length=200)


class GatewayTokenizeOut(BaseModel):
    token: str
    provider: str
    brand: str
    last4: str
    exp_month: int
    exp_year: int
    holder_name: str | None = None


class GatewayChargeIn(BaseModel):
    token: str = Field(..., min_length=1, max_length=255)
    amount_cents: int = Field(..., ge=1, le=100_000_000)
    currency: str = Field(default="usd", max_length=8)
    description: str | None = Field(default=None, max_length=200)


class GatewayChargeOut(BaseModel):
    id: str
    provider: str
    status: str
    amount_cents: int
    currency: str
    description: str | None = None


class PaymentMethodOut(BaseModel):
    id: str
    user_id: str
    brand: str
    last4: str
    exp_month: int
    exp_year: int
    holder_name: str | None = None
    is_default: bool
    provider: str
    verified: bool
    expired: bool = False


class BudgetOut(BaseModel):
    plan: str
    balance_cents: int
    balance_dollars: float
    currency: str = "usd"


class PlanGrantIn(BaseModel):
    plan: str = Field(..., pattern=r"^(free|pro)$")
    add_credit_cents: int = Field(default=0, ge=0, le=1_000_000)
    note: str | None = Field(default=None, max_length=500)
