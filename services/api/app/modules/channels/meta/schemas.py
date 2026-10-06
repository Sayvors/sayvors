"""Meta integration API schemas."""
from pydantic import BaseModel, Field


class MetaConnectionOut(BaseModel):
    id: str
    provider: str
    connection_type: str
    meta_business_id: str | None = None
    scopes: list[str] = []
    status: str
    last_validated_at: str | None = None
    last_successful_api_call_at: str | None = None
    last_webhook_received_at: str | None = None
    created_at: str


class MetaConnectionListResponse(BaseModel):
    connections: list[MetaConnectionOut]


class MetaConnectResponse(BaseModel):
    """Entry point for the provider authorization flow."""

    provider: str
    # Facebook/Instagram: full dialog URL to open. WhatsApp: FB.login params.
    auth_url: str | None = None
    fb_app_id: str | None = None
    fb_config_id: str | None = None
    graph_api_version: str | None = None
    solution_id: str | None = None
    state: str


class MetaAssetOut(BaseModel):
    id: str
    provider: str
    asset_type: str
    external_asset_id: str
    parent_asset_id: str | None = None
    name: str | None = None
    username: str | None = None
    phone: str | None = None
    active: bool
    status: str


class MetaAssetListResponse(BaseModel):
    assets: list[MetaAssetOut]


class MetaAssetSelect(BaseModel):
    asset_ids: list[str] = Field(..., min_length=1, max_length=50)


class MetaValidateResponse(BaseModel):
    connection_id: str
    status: str
    detail: str | None = None
    checked_at: str


class MetaWhatsAppSession(BaseModel):
    """Embedded Signup v4 session completion posted by the frontend."""

    state: str
    code: str | None = Field(None, description="Auth code from authResponse")
    waba_id: str | None = None
    phone_number_id: str | None = None
    business_id: str | None = None
    # 6-digit WhatsApp two-step-verification PIN. Meta REFUSES to register a
    # number without it, so a connect without a PIN yields a number that
    # cannot send. Optional here (the tenant can add it afterwards inside the
    # 14-day window) but surfaced loudly when registration fails.
    pin: str | None = Field(
        None,
        pattern=r"^\d{6}$",
        description="6-digit two-step verification PIN for the number",
    )
    mode: str | None = Field(
        None,
        pattern=r"^(standard|coexistence)$",
        description="Onboarding mode: 'standard' (new number) or 'coexistence' (existing Business app number)",
    )


class MetaRegisterNumberRequest(BaseModel):
    """Retry number registration — Meta allows this for 14 days after signup."""

    pin: str = Field(..., pattern=r"^\d{6}$")


class WhatsAppProfileOut(BaseModel):
    about: str | None = None
    address: str | None = None
    description: str | None = None
    email: str | None = None
    websites: list[str] = []
    vertical: str | None = None
    profile_picture_url: str | None = None
    # When the live Graph read failed, `stale` marks the persisted copy.
    synced_at: str | None = None
    stale: bool = False


class WhatsAppUsageOut(BaseModel):
    """Sayvors tenant messaging quota — never Meta's messaging tier."""

    used_this_month: int
    monthly_limit: int
    plan: str


class WhatsAppProfileUpdate(BaseModel):
    about: str | None = Field(None, max_length=139)
    address: str | None = Field(None, max_length=512)
    description: str | None = Field(None, max_length=512)
    email: str | None = Field(None, max_length=128)
    websites: list[str] | None = Field(None, max_length=2)
    vertical: str | None = Field(None, max_length=64)
