from pydantic import BaseModel, Field


class ChannelCreate(BaseModel):
    platform: str = Field(..., description="facebook, instagram, x, telegram, whatsapp, linkedin")
    access_token: str | None = None
    platform_user_id: str | None = None
    display_name: str | None = None


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
