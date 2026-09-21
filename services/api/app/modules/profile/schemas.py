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
    plan: str = "pro"
    member_since: str
    feedback: dict[str, int] = {}


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


class FeedbackRequest(BaseModel):
    category: str = Field(..., min_length=1, max_length=50)
    stars: int = Field(..., ge=1, le=5)


class UsageItem(BaseModel):
    label: str
    used: int
    total: int
    unit: str
    percent: float


class UsageResponse(BaseModel):
    items: list[UsageItem]
    cached: bool = False
