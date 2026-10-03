from pydantic import BaseModel, Field


class ProfileResponse(BaseModel):
    id: str
    first_name: str
    last_name: str
    email: str
    email_verified: bool
    onboarded: bool
    bio: str | None = None
    business_name: str | None = None
    business_type: str | None = None
    business_sells: str | None = None
    business_doesnt_sell: str | None = None
    business_description: str | None = None
    phone: str | None = None
    country: str | None = None
    theme: str = "light"
    language: str = "en"
    response_style: str = "concise"
    voice_replies: str = "off"
    plan: str = "pro"
    member_since: str
    # Actual service shape: a list of {emoji_rating, message, created_at}
    # rows. (Was declared dict[str, int] — every profile response 500'd on
    # serialization because of it.)
    feedback: list[dict] = []


class ProfileUpdateRequest(BaseModel):
    first_name: str | None = Field(default=None, min_length=2, max_length=100)
    last_name: str | None = Field(default=None, min_length=2, max_length=100)
    bio: str | None = Field(default=None, max_length=2000)
    business_name: str | None = Field(default=None, max_length=255)
    business_type: str | None = Field(default=None, max_length=100)
    business_sells: str | None = Field(default=None, max_length=2000)
    business_doesnt_sell: str | None = Field(default=None, max_length=2000)
    business_description: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=50)
    country: str | None = Field(default=None, max_length=8, description="Account-wide ISO country code, e.g. SA")


class PreferencesUpdateRequest(BaseModel):
    theme: str = Field(..., pattern="^(light|dark|system)$")
    language: str = Field(..., pattern="^(en|es|fr|de|ar|zh|ja|ur)$")


class ResponseStyleUpdateRequest(BaseModel):
    """Tenant-level WhatsApp response style ("concise" | "human").

    Extensible string, not a boolean — new styles are added to the pattern
    without a migration.
    """

    response_style: str = Field(..., pattern="^(concise|human)$")


class VoiceRepliesUpdateRequest(BaseModel):
    """Tenant-level WhatsApp voice replies tier.

    "off" never sends voice notes; "simple"/"advanced" allow them when the
    customer seems confused. The engine behind each tier is admin-managed
    (voice_model_configs) — tenants never see provider names.
    """

    voice_replies: str = Field(..., pattern="^(off|simple|advanced)$")


class FeedbackRequest(BaseModel):
    emoji_rating: int = Field(..., ge=1, le=5)
    message: str | None = Field(None, max_length=2000)


class UsageItem(BaseModel):
    label: str
    used: int
    total: int
    unit: str
    percent: float


class UsageResponse(BaseModel):
    items: list[UsageItem]
    cached: bool = False


class BusinessProfileData(BaseModel):
    id: str
    summary: str | None = None
    domain: str | None = None
    products_services: str | None = None
    not_offered_and_policies: str | None = None
    audience_languages: str | None = None
    source: str = "auto"
    generated_at: str | None = None
    updated_at: str | None = None


class BusinessProfileResponse(BaseModel):
    profile: BusinessProfileData | None = None


class BusinessProfileUpdateRequest(BaseModel):
    summary: str | None = Field(None, max_length=2000)
    domain: str | None = Field(None, max_length=200)
    products_services: str | None = Field(None, max_length=2000)
    not_offered_and_policies: str | None = Field(None, max_length=2000)
    audience_languages: str | None = Field(None, max_length=500)
