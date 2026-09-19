from pydantic import BaseModel, Field


class ChannelCreate(BaseModel):
    platform: str = Field(..., description="facebook, instagram, x, telegram, whatsapp, linkedin, google_reviews")
    access_token: str | None = None
    refresh_token: str | None = None
    platform_user_id: str | None = Field(None, description="Platform account id (Google: Business account id)")
    display_name: str | None = None
    location_id: str | None = Field(None, description="Google Business Profile location id (google_reviews only)")
    webhook_secret: str | None = None


class ChannelResponse(BaseModel):
    id: str
    platform: str
    platform_user_id: str | None = None
    display_name: str | None = None
    status: str
    avatar_url: str | None = None
    created_at: str


class ChannelListResponse(BaseModel):
    channels: list[ChannelResponse]
    total: int


class VerificationRequest(BaseModel):
    method: str = Field(..., pattern="^(phone|sms|email|postcard|video|live_video)$")
    contact_target: str | None = Field(None, max_length=255)


class VerificationResponse(BaseModel):
    channel_id: str
    status: str
    method: str | None
    contact_target: str | None
    attempts: int
    requested_at: str | None
    verified_at: str | None
    provider_managed: bool = True


class ServiceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    category: str = Field("Custom", min_length=1, max_length=120)
    description: str | None = Field(None, max_length=500)
    is_offered: bool = True
    source: str = Field("custom", pattern="^(custom|google)$")


class ServiceUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    category: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = Field(None, max_length=500)
    is_offered: bool | None = None


class ServiceResponse(BaseModel):
    id: str
    channel_id: str
    name: str
    category: str
    description: str | None
    is_offered: bool
    source: str


class ChannelMessageSend(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)
    content_type: str = "text"


class ChannelMessageResponse(BaseModel):
    id: str
    channel_id: str
    platform_message_id: str | None = None
    direction: str
    content: str
    content_type: str
    status: str
    error: str | None = None
    created_at: str


class ChannelMessageListResponse(BaseModel):
    messages: list[ChannelMessageResponse]
    total: int


class AutoReplyConfigUpdate(BaseModel):
    enabled: bool | None = None
    tone: str | None = Field(None, description="friendly, professional, apologetic, playful, ...")
    databank_id: str | None = Field(None, description="Databank linked for grounding; null to unlink")
    min_rating_auto: int | None = Field(None, ge=1, le=5, description="Ratings below this are queued for approval")
    model: str | None = Field(None, description="LLM catalog model id, e.g. openai:gpt-4o-mini")
    approval_mode: str | None = Field(None, pattern="^(auto|approval)$", description="auto = post above threshold; approval = all replies wait for human approval")
    custom_instructions: str | None = Field(None, max_length=2000, description="Brand voice / house rules injected into every reply prompt; empty to clear")
    dialect: str | None = Field(None, max_length=30, description="Arabic dialect catalog code or 'auto'")
    reply_language: str | None = Field(None, pattern="^(match|en|ar)$", description="match = reply in the review's language; en/ar = force a language")
    promo_product_mentions: bool | None = Field(None, description="Allow promotional product mentions in replies")
    promo_links: bool | None = Field(None, description="Allow promotional links in replies")
    promo_only_relevant: bool | None = Field(None, description="Only promote when relevant to the review")
    promo_max_ctas: int | None = Field(None, ge=0, le=5, description="Maximum promotional CTAs per reply")


class AutoReplyConfigResponse(BaseModel):
    channel_id: str
    enabled: bool
    tone: str
    databank_id: str | None
    min_rating_auto: int
    model: str
    approval_mode: str = "auto"
    custom_instructions: str | None = None
    dialect: str = "auto"
    reply_language: str = "match"
    promo_product_mentions: bool = False
    promo_links: bool = False
    promo_only_relevant: bool = True
    promo_max_ctas: int = 1


class ReviewReplyResponse(BaseModel):
    id: str
    channel_id: str
    review_id: str
    rating: int
    review_text: str | None
    reviewer_name: str | None
    reply_text: str
    status: str
    generation_attempt: int = 1
    error: str | None
    created_at: str
    review_url: str | None = None


class ReviewReplyListResponse(BaseModel):
    replies: list[ReviewReplyResponse]
    pending: int


class ReviewReplyGenerate(BaseModel):
    """Request to draft a reply for a review that has no reply row yet."""

    review_id: str = Field(..., min_length=1, max_length=500)
    rating: int = Field(..., ge=1, le=5)
    review_text: str | None = Field(None, max_length=4000)
    reviewer_name: str | None = Field(None, max_length=255)
    custom_text: str | None = Field(
        None,
        max_length=2000,
        description="Merchant-typed reply text; when provided the LLM is skipped",
    )


class ReviewReplyEdit(BaseModel):
    reply_text: str = Field(..., min_length=1, max_length=4000)
