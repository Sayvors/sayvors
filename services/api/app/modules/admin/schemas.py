from pydantic import BaseModel, Field


class AdminOverview(BaseModel):
    users_total: int
    users_verified: int
    signups_last_7d: int
    connections: int
    last_synced_at: str | None = None
    reviews_total: int
    posts_total: int
    posts_by_status: dict[str, int] = {}
    databanks_total: int
    documents_total: int
    outbox_pending: int
    outbox_failed: int
    ingest_failed: int


class AdminTenant(BaseModel):
    id: str
    email: str
    first_name: str | None = None
    last_name: str | None = None
    email_verified: bool = False
    created_at: str | None = None
    has_connection: bool = False
    listing_name: str | None = None
    last_synced_at: str | None = None
    reviews: int = 0
    posts: int = 0
    databanks: int = 0


class AdminTenantList(BaseModel):
    total: int
    items: list[AdminTenant]


class AdminTenantDetail(AdminTenant):
    recent_reviews: list[dict] = []
    recent_posts: list[dict] = []


class LlmProviderStatus(BaseModel):
    provider: str
    key_source: str  # database | none | disabled
    enabled: bool = True
    has_key: bool = False
    models: list["LlmModelStatus"] = []


class LlmModelStatus(BaseModel):
    id: str
    name: str
    enabled: bool = True
    tested_ok: bool | None = None
    tested_at: str | None = None
    custom: bool = False


class LlmModelUpdate(BaseModel):
    enabled: bool


class LlmModelCreate(BaseModel):
    id: str = Field(..., min_length=3, max_length=100)
    name: str = Field(..., min_length=1, max_length=120)
    provider: str = Field(..., min_length=1, max_length=32)
    api_model: str = Field(..., min_length=1, max_length=200)
    api_url: str | None = Field(None, max_length=500)
    context_window: int = Field(32000, ge=1024, le=2000000)
    max_output: int = Field(4096, ge=128, le=200000)
    supports_stream: bool = True
    enabled: bool = True


class LlmModelTestResult(BaseModel):
    model_id: str
    ok: bool
    latency_ms: int = 0
    detail: str = ""
    reply: str = ""


class RemoteModel(BaseModel):
    id: str
    name: str


class SavedModel(BaseModel):
    id: str
    name: str
    provider: str
    api_model: str
    enabled: bool = True
    custom: bool = False
    tested_ok: bool | None = None
    tested_at: str | None = None


class LlmProviderUpdate(BaseModel):
    api_key: str | None = Field(None, max_length=500)
    enabled: bool | None = None


class LlmTestResult(BaseModel):
    provider: str
    ok: bool
    latency_ms: int = 0
    detail: str = ""


class HealthService(BaseModel):
    name: str
    kind: str
    ok: bool
    latency_ms: int = 0
    detail: str = ""
    enabled: bool = True
    key_source: str = ""


class HealthFailure(BaseModel):
    source: str
    type: str
    message: str = ""
    at: str | None = None


class AdminHealth(BaseModel):
    status: str
    checked_at: str | None = None
    uptime_seconds: int = 0
    probe: bool = False
    services: list[HealthService] = []
    recent_failures: list[HealthFailure] = []
