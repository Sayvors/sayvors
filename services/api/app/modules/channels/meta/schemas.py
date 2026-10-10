"""Meta integration API schemas."""
from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl


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
    hours: dict[str, list[dict[str, str]]] | None = None
    # When the live Graph read failed, `stale` marks the persisted copy.
    synced_at: str | None = None
    stale: bool = False


class InstagramProfileOut(BaseModel):
    """Live Instagram business profile - READ ONLY.

    Meta's IG User reference states updating is not supported, so there is no
    matching Update schema on purpose. See InstagramAdapter.get_business_profile.
    """

    username: str | None = None
    name: str | None = None
    biography: str | None = None
    website: str | None = None
    profile_picture_url: str | None = None
    followers_count: int = 0
    follows_count: int = 0
    media_count: int = 0
    # What Sayvors knows for certain. Meta does not expose `account_type` on
    # the IG User node (requesting it fails the whole read), so the UI reports
    # the asset state we store at connect time instead of guessing.
    status: str | None = None
    eligibility: str | None = None
    # The Facebook Page the IG account hangs off, so the UI can say which Page
    # it belongs to (IG is always Page-backed here).
    parent_page_id: str | None = None
    parent_page_name: str | None = None
    # When the live Graph read failed, stale marks the persisted copy.
    synced_at: str | None = None
    stale: bool = False


class InstagramPerson(BaseModel):
    """One person who engaged with the account.

    source is comment (live from Graph) or dm (from our own inbox). Every row
    carries a real instagram.com profile link because we hold their username -
    which is exactly what a follower list could never give us.
    """

    source: str
    ig_id: str | None = None
    username: str | None = None
    name: str | None = None
    text: str | None = None
    like_count: int = 0
    occurred_at: str | None = None
    media_id: str | None = None
    permalink: str | None = None
    profile_url: str | None = None


class InstagramDemographics(BaseModel):
    """Aggregate follower demographics. vailable is False with a reason
    when the insights scope is missing or the account has under 100 followers."""

    available: bool = False
    reason: str | None = None
    age: list[dict] = []
    gender: list[dict] = []
    cities: list[dict] = []
    countries: list[dict] = []


class InstagramReplyOut(BaseModel):
    id: str | None = None
    text: str | None = None
    username: str | None = None
    timestamp: str | None = None
    like_count: int = 0
    hidden: bool = False


class InstagramCommentOut(BaseModel):
    id: str | None = None
    text: str | None = None
    username: str | None = None
    name: str | None = None
    ig_id: str | None = None
    like_count: int = 0
    timestamp: str | None = None
    hidden: bool = False
    media_id: str | None = None
    profile_url: str | None = None
    replies: list[InstagramReplyOut] = []


class InstagramChildMediaOut(BaseModel):
    """One slide of a carousel — the modal flips through these."""

    id: str | None = None
    media_type: str | None = None
    media_url: str | None = None
    thumbnail_url: str | None = None


class InstagramPostOut(BaseModel):
    id: str | None = None
    caption: str | None = None
    media_type: str | None = None
    # FEED / REELS / STORY — reels get their own badge and insights set.
    media_product_type: str | None = None
    media_url: str | None = None
    # Static poster frame for videos/carousels — a video's media_url is the
    # file itself, useless as a grid thumbnail.
    thumbnail_url: str | None = None
    permalink: str | None = None
    timestamp: str | None = None
    like_count: int = 0
    comments_count: int = 0
    children: list[InstagramChildMediaOut] = []
    comments: list[InstagramCommentOut] = []


class InstagramPostsOut(BaseModel):
    posts: list[InstagramPostOut] = []
    unavailable: str | None = None


class InstagramStoryOut(BaseModel):
    """The account's own live story — the only stories edge the API has."""

    id: str | None = None
    media_type: str | None = None
    media_url: str | None = None
    timestamp: str | None = None


class InstagramStoriesOut(BaseModel):
    stories: list[InstagramStoryOut] = []


class InstagramMediaInsightsOut(BaseModel):
    """Owner-only per-post insights; fields stay None when Meta refuses."""

    available: bool = False
    reason: str | None = None
    impressions: int | None = None
    reach: int | None = None
    saves: int | None = None
    shares: int | None = None
    views: int | None = None


class InstagramStoredCommentOut(BaseModel):
    """A stored comment on the tenant's own media — the inbox row.

    comment_id/parent_comment_id are the PLATFORM ids (threading + Graph
    addressing); id is our row id. deleted_at set means the comment no
    longer exists on Instagram (deleted via Sayvors, or a lazy probe 404'd
    — Meta sends no delete webhook)."""

    id: str
    comment_id: str | None = None
    parent_comment_id: str | None = None
    media_id: str | None = None
    direction: str
    content: str
    author_id: str | None = None
    author_name: str | None = None
    like_count: int = 0
    hidden: bool = False
    status: str
    error: str | None = None
    platform_timestamp: datetime | None = None
    deleted_at: datetime | None = None
    created_at: datetime


class InstagramCommentsOut(BaseModel):
    comments: list[InstagramStoredCommentOut] = []


class InstagramCommentReplyIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=2200)


class InstagramCommentHideIn(BaseModel):
    hidden: bool = True


class InstagramCommentActionOut(BaseModel):
    ok: bool = True
    hidden: bool | None = None


class InstagramAudienceOut(BaseModel):
    people: list[InstagramPerson] = []
    demographics: InstagramDemographics = InstagramDemographics()
    comments_unavailable: str | None = None


class InstagramPublishIn(BaseModel):
    """Post images to the tenant's own feed. One url is a single post;
    several become a carousel. Meta fetches these urls itself, so they
    must be publicly reachable — storage's public media path qualifies.

    location_id is a Facebook Page-format place id (from the locations
    search); share_to_facebook cross-posts to the linked Page; alt_text
    is Meta's accessibility layer for image posts. story_image_urls are
    9:16 images published as stories AFTER the feed post — the client
    crops them; Meta rejects anything not 9:16."""

    image_urls: list[HttpUrl] = Field(min_length=1, max_length=10)
    caption: str = Field(default="", max_length=2200)
    location_id: str | None = Field(None, max_length=64)
    share_to_facebook: bool = False
    alt_text: str | None = Field(None, max_length=1000)
    story_image_urls: list[HttpUrl] | None = Field(None, max_length=10)


class InstagramPublishOut(BaseModel):
    """The published post's platform media id — the same id the posts
    grid lists, so the composer can deep-link to it once the grid
    refreshes. story_media_ids lists the story posts published alongside
    (empty when none were requested)."""

    media_id: str
    story_media_ids: list[str] = []


class InstagramPublishingLimitOut(BaseModel):
    """Meta's rolling 24h publishing quota for this account (50/day cap).
    quota_total is 0 when Meta refused the read — the UI hides the line."""

    quota_total: int = 0
    quota_usage: int = 0


class InstagramLocationOut(BaseModel):
    id: str
    name: str


class InstagramLocationsOut(BaseModel):
    """Place search results for the location picker; empty when the
    account's token can't search (the UI then hides the field)."""

    locations: list[InstagramLocationOut] = []


class InstagramCaptionSuggestIn(BaseModel):
    """What the image shows and anything to steer the caption — the
    current draft rides along so the model continues the tenant's
    voice rather than overwriting it blindly."""

    hint: str = Field(default="", max_length=500)
    current_caption: str = Field(default="", max_length=2200)


class InstagramCaptionOut(BaseModel):
    caption: str


class FacebookProfileOut(BaseModel):
    """The tenant's OWN Page — read-only; Meta has no profile-write API."""

    id: str
    name: str | None = None
    link: str | None = None
    profile_picture_url: str | None = None
    fan_count: int = 0
    followers_count: int = 0


class FacebookPostOut(BaseModel):
    id: str
    message: str | None = None
    permalink_url: str | None = None
    full_picture: str | None = None
    from_name: str | None = None
    like_count: int = 0
    comments_count: int = 0
    created_time: str | None = None
    images: list[str] = []


class FacebookPostsOut(BaseModel):
    posts: list[FacebookPostOut] = []
    unavailable: str | None = None


class FacebookScheduledPostOut(BaseModel):
    id: str
    scheduled_publish_time: int | None = None  # unix seconds


class FacebookScheduledOut(BaseModel):
    posts: list[FacebookScheduledPostOut] = []


class FacebookPublishIn(BaseModel):
    """Publish to the tenant's own Page feed. Exactly one of link /
    image_urls per post (a bare message is a text post); schedule_at
    turns it into a scheduled post — Meta requires 10 minutes to ~6
    months ahead. Meta fetches image urls itself, so they must be
    publicly reachable — storage's public media path qualifies."""

    message: str = Field(default="", max_length=5000)
    link: HttpUrl | None = None
    image_urls: list[HttpUrl] | None = Field(None, max_length=10)
    schedule_at: datetime | None = None


class FacebookPublishOut(BaseModel):
    """post_id is the feed post id (pageid_postid) — the same id the
    posts grid lists. Photo ids ride photo_ids when single-photo
    publishing returned them. scheduled=True means Meta accepted a
    scheduled post: nothing is live yet."""

    post_id: str | None = None
    photo_ids: list[str] = []
    scheduled: bool = False


class FacebookStoredCommentOut(BaseModel):
    """A stored comment on the tenant's own Page posts — the inbox row.
    media_id holds the FB post id (pageid_postid)."""

    id: str
    comment_id: str | None = None
    parent_comment_id: str | None = None
    media_id: str | None = None
    direction: str
    content: str
    author_id: str | None = None
    author_name: str | None = None
    like_count: int = 0
    hidden: bool = False
    status: str
    error: str | None = None
    platform_timestamp: datetime | None = None
    deleted_at: datetime | None = None
    created_at: datetime


class FacebookCommentsOut(BaseModel):
    comments: list[FacebookStoredCommentOut] = []


class FacebookCommentReplyIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000)


class FacebookCommentHideIn(BaseModel):
    hidden: bool = True


class FacebookCommentActionOut(BaseModel):
    ok: bool = True
    hidden: bool | None = None


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
    hours: dict[str, list[dict[str, str]]] | None = None
