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
    # ISO datetime: auto-delete our copy (Google follows its own lifecycle).
    delete_at: str | None = None
    # ISO datetime: event/offer end — Google takes ended posts down itself.
    end_date: str | None = None
    # ISO datetime: event start (required by Google for events).
    start_date: str | None = None
    # Offer headline code (voucherCode). Terms travel inside the caption —
    # Localith's wrapper exposes no separate terms field.
    coupon_code: str | None = Field(None, max_length=64)
    terms_conditions: str | None = Field(None, max_length=2000)


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
    # ISO datetime to (re)schedule auto-deletion; explicit null cancels it.
    # Absent key = untouched (router passes exclude_unset).
    delete_at: str | None = None
    end_date: str | None = None
    start_date: str | None = None
    coupon_code: str | None = Field(None, max_length=64)
    terms_conditions: str | None = Field(None, max_length=2000)


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
    delete_at: str | None = None
    end_date: str | None = None
    start_date: str | None = None
    coupon_code: str | None = None
    terms_conditions: str | None = None
    google_post_id: str | None = None
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
    skipped: int = 0
    retried: int = 0
    deleted: int = 0


class AiDraftRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    post_type: str = Field("update", pattern="^(update|offer|event)$")
    business_name: str | None = Field(None, max_length=255)


class AiDraftResponse(BaseModel):
    description: str = ""
    tags: list[str] = []
    keywords: list[str] = []
