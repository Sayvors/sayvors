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
