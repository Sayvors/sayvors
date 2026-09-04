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


class AutoReplyConfigResponse(BaseModel):
    channel_id: str
    enabled: bool
    tone: str
    databank_id: str | None
    min_rating_auto: int
    model: str


class ReviewReplyResponse(BaseModel):
    id: str
    channel_id: str
    review_id: str
    rating: int
    review_text: str | None
    reviewer_name: str | None
    reply_text: str
    status: str
    error: str | None
    created_at: str


class ReviewReplyListResponse(BaseModel):
    replies: list[ReviewReplyResponse]
    pending: int
