from pydantic import BaseModel, Field


class PostCreate(BaseModel):
    listing_id: str = Field(..., min_length=1, max_length=64)
    location_name: str = Field("", max_length=255)
    business_name: str = Field("Sayvors", max_length=255)
    title: str = Field("", max_length=500)
    post_type: str = Field("update", pattern="^(update|event|offer)$")
    description: str = Field("", max_length=1500)
    tags: list[str] = []
    keywords: list[str] = []
    image_urls: list[str] = []
    cta_type: str | None = Field(None, max_length=32)
    cta_url: str | None = Field(None, max_length=1000)
    # "publish" -> publish to Google immediately; "schedule" -> queue for later.
    action: str = Field("publish", pattern="^(publish|schedule|draft)$")
    scheduled_on: str | None = None  # ISO datetime, required for schedule


class PostUpdate(BaseModel):
    location_name: str | None = Field(None, max_length=255)
    business_name: str | None = Field(None, max_length=255)
    title: str | None = Field(None, max_length=500)
    post_type: str | None = Field(None, pattern="^(update|event|offer)$")
    description: str | None = Field(None, max_length=1500)
    tags: list[str] | None = None
    keywords: list[str] | None = None
    image_urls: list[str] | None = None
    cta_type: str | None = Field(None, max_length=32)
    cta_url: str | None = Field(None, max_length=1000)
    status: str | None = Field(None, pattern="^(draft|scheduled|published|archived)$")
    scheduled_on: str | None = None


class PostOut(BaseModel):
    id: str
    listing_id: str
    location_name: str | None = None
    business_name: str = ""
    title: str = ""
    post_type: str = "update"
    description: str = ""
    tags: list[str] = []
    keywords: list[str] = []
    image_urls: list[str] = []
    cta_type: str | None = None
    cta_url: str | None = None
    status: str
    scheduled_on: str | None = None
    published_at: str | None = None
    error: str | None = None
    created_at: str


class PublishResult(BaseModel):
    post: PostOut
    google_published: bool
    images_sent: int
    images_skipped: int


class SyncResult(BaseModel):
    checked: int
    published: int
    failed: int
    errors: list[str] = []
