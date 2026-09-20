from pydantic import BaseModel, Field


class MediaCreate(BaseModel):
    listing_id: str = Field(..., min_length=1, max_length=64)
    image_url: str = Field(..., min_length=8, max_length=2000)
    type: str = Field("PHOTO", pattern="^(PHOTO|VIDEO)$")
    category: str = Field("EXTERIOR", max_length=32)
    caption: str = Field("", max_length=500)
    # "publish" -> photo goes live now (inside a Google post);
    # "schedule" -> queued for later; "draft" -> library only.
    action: str = Field("publish", pattern="^(publish|schedule|draft)$")
    scheduled_on: str | None = None  # ISO datetime, required for schedule
    # ISO datetime: auto-delete our copy (Google follows its own lifecycle).
    delete_at: str | None = None
    # post = inside a Google post (wired via Localith). gallery / profile =
    # stored intent only until per-tenant native Google lands.
    publish_method: str = Field("post", pattern="^(post|gallery|profile)$")


class MediaUpdate(BaseModel):
    category: str | None = Field(None, max_length=32)
    caption: str | None = Field(None, max_length=500)
    is_profile: bool | None = None
    is_cover: bool | None = None
    status: str | None = Field(None, pattern="^(draft|scheduled|published|archived)$")
    scheduled_on: str | None = None
    # ISO datetime to (re)schedule auto-deletion; explicit null cancels it.
    # Absent key = untouched (router passes exclude_unset).
    delete_at: str | None = None
    publish_method: str | None = Field(None, pattern="^(post|gallery|profile)$")


class MediaOut(BaseModel):
    id: str
    listing_id: str
    image_url: str
    type: str
    category: str
    caption: str = ""
    status: str
    scheduled_on: str | None = None
    published_at: str | None = None
    delete_at: str | None = None
    publish_method: str = "post"
    google_post_id: str | None = None
    is_profile: bool = False
    is_cover: bool = False
    error: str | None = None
    created_at: str


class MediaPublishResult(BaseModel):
    media: MediaOut
    google_published: bool


class MediaSyncResult(BaseModel):
    checked: int
    published: int
    failed: int
    errors: list[str] = []
    skipped: int = 0
    retried: int = 0
    deleted: int = 0
