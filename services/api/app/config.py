from pydantic_settings import BaseSettings
from pydantic import field_validator


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/sayvors"
    DATABASE_READER_URL: str = ""  # empty = reads also hit DATABASE_URL (no replica yet)
    DB_POOL_MODE: str = "session"  # session | transaction — PgBouncer pool mode
    # AsyncPG pool: workers hold sessions across network calls (Localith,
    # Groq), so size generously and fail fast instead of hanging forever.
    DB_POOL_SIZE: int = 5
    DB_POOL_MAX_OVERFLOW: int = 5
    DB_POOL_TIMEOUT_SECONDS: int = 30
    DB_STATEMENT_TIMEOUT_MS: int = 30000  # 30s — kills runaway queries
    DB_IDLE_IN_TX_TIMEOUT_MS: int = 60000  # 60s — kills stuck transactions
    # A query waiting on a row lock is holding a pool connection the whole
    # time. At 1M tenants the hot rows (wallet, jobs, thread counters) are
    # contended, so fail the wait fast and let the caller retry instead of
    # pinning a connection for the full statement timeout.
    DB_LOCK_TIMEOUT_MS: int = 5000  # 5s
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_EXPIRATION_MINUTES: int = 15
    JWT_REFRESH_EXPIRATION_DAYS: int = 7
    # "production" arms the fail-closed startup validation below.
    ENVIRONMENT: str = "development"
    VERSION: str = "0.1.0"
    GLITCHTIP_DSN: str = ""
    GLITCHTIP_SECRET_KEY: str = ""
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]
    # Optional regex for rotating dev-tunnel origins (e.g. free-tier ngrok
    # gives the frontend a new subdomain on every restart). Starlette echoes
    # the actual origin for regex matches, so credentials still work.
    CORS_ORIGIN_REGEX: str | None = None
    # Queue/poll workers (WhatsApp AI replies, reviews auto-reply, syncs,
    # publishers, Kafka consumers, outbox drainer) run inside the API process
    # when true — the dev default so one uvicorn process is self-sufficient.
    # The worker deployment (docker-compose worker service, `python -m
    # app.workers`) sets this false on the api so HTTP traffic can never
    # delay message replies.
    RUN_BACKGROUND_WORKERS: bool = True
    # Comma-separated job lane allowlist for the worker process. Empty = all
    # lanes. Lets a single lane be scaled independently (e.g. JOB_LANES=realtime
    # on a dedicated replica) without running every lane. Unknown names fail fast.
    JOB_LANES: str = ""
    REDIS_URL: str = "redis://localhost:6379/0"
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    # pgvector-backed semantic search. None = auto: on in production, off
    # everywhere else so a development database without the pgvector
    # extension still boots and can run the whole migration chain. Set it
    # explicitly to force the behaviour in either direction.
    EMBEDDINGS_ENABLED: bool | None = None

    # ── Auth security ────────────────────────────────────
    MAX_LOGIN_ATTEMPTS: int = 5
    LOCKOUT_MINUTES: int = 15
    # Fail closed on auth-critical paths (rate limits, token blacklist) when
    # Redis is unavailable. Set to false ONLY for local dev without Redis.
    AUTH_RATE_LIMIT_FAIL_CLOSED: bool = True
    # IP addresses/CIDRs of reverse proxies whose X-Forwarded-For/X-Real-IP
    # headers we trust. Requests from any other peer use the socket address.
    TRUSTED_PROXIES: list[str] = ["127.0.0.1", "::1"]
    # Retention cleanup interval (seconds) for login_attempts / refresh_tokens.
    RETENTION_CLEANUP_INTERVAL_SECONDS: int = 6 * 3600
    RETENTION_DELETE_BATCH_SIZE: int = 1000
    CSRF_COOKIE_NAME: str = "csrf_token"
    REFRESH_COOKIE_NAME: str = "refresh_token"
    ACCESS_COOKIE_NAME: str = "access_token"
    REFRESH_COOKIE_MAX_AGE: int = 60 * 60 * 24 * 7  # 7 days
    ACCESS_COOKIE_MAX_AGE: int = 15 * 60  # 15 minutes, matches JWT access expiry
    # Parent domain shared by the SPA and the API (e.g. ".sayvors.com").
    # Lets the SPA origin read the non-httpOnly CSRF cookie for the
    # X-CSRF-Token double-submit header in split-domain deployments.
    # None = host-only cookies (local dev). Defaults to .sayvors.com so that
    # cookies set by api.sayvors.com are also sent to web.sayvors.com and vice
    # versa. Local dev: set COOKIE_DOMAIN= in .env to get host-only cookies.
    COOKIE_DOMAIN: str | None = ".sayvors.com"

    @property
    def embeddings_enabled(self) -> bool:
        """Whether pgvector-backed semantic search runs in this process.

        Auto mode keys off ``ENVIRONMENT``: a staging or production deployment
        without pgvector would silently degrade every databank to
        keyword-only, so those default on and the migration fails loudly if
        the extension is missing. Development and test default off so a
        database without pgvector still runs the app.
        """
        if self.EMBEDDINGS_ENABLED is not None:
            return self.EMBEDDINGS_ENABLED
        return self.ENVIRONMENT not in {"development", "test"}

    @field_validator("COOKIE_DOMAIN")
    @classmethod
    def _cookie_domain(cls, v: str | None) -> str | None:
        # Empty string means host-only (for local dev on localhost)
        if v == "":
            return None
        return v
    # Cookie transport flags. Both cookies are hardcoded Secure/SameSite=None
    # by default, which is correct in production and silently breaks local dev:
    # a browser refuses a Secure cookie over plain http, so the CSRF cookie
    # never lands and EVERY non-GET call fails 403 "CSRF validation failed"
    # while GETs (which skip the check) keep working — a confusing half-broken
    # app. Set COOKIE_SECURE=false for http://localhost / ngrok-over-http dev.
    COOKIE_SECURE: bool = True
    COOKIE_SAMESITE: str = "none"  # none | lax | strict
    ALLOWED_HOSTS: list[str] = ["localhost", "127.0.0.1"]

    # ── Logging ─────────────────────────────────────────
    # "" = auto: readable console when stdout is a terminal, one-JSON-object-per-
    # line when it is piped (Docker, log shippers, aggregators). Force either
    # shape with "console" / "json". Anything else falls back to auto.
    LOG_FORMAT: str = ""

    # ── File uploads ────────────────────────────────────
    UPLOAD_DIR: str = "./data/uploads"
    MAX_UPLOAD_SIZE_MB: int = 100
    # Public media files (photo uploads that go to Google): stored under
    # UPLOAD_DIR/media and served at <api-origin>/media-files/... so the
    # provider can fetch them by URL. Mounted on a docker volume so
    # redeploys never wipe them.
    MEDIA_DIR: str = "./data/uploads/media"
    MEDIA_PUBLIC_PATH: str = "/media-files"
    MEDIA_MAX_MB: int = 25
    # Storage (optional; empty = local disk). GCS remains supported; S3 can
    # be selected independently for public media and private documents. S3
    # private docs require their own bucket; never reuse the media fallback.
    #   GCS_PUBLIC_BUCKET  — owner photos/videos (uniform PUBLIC access).
    #                        The provider fetches media from public URLs.
    #   GCS_PRIVATE_BUCKET — databank docs/scrapes/exports (private).
    # Auth is standard: GOOGLE_APPLICATION_CREDENTIALS points at the
    # service-account JSON (mounted as a secret, never committed).
    GCS_PUBLIC_BUCKET: str = ""
    GCS_PRIVATE_BUCKET: str = ""
    AWS_S3_BUCKET: str = ""  # shared default; per-purpose buckets override it
    S3_MEDIA_BUCKET: str = ""
    S3_DOCS_BUCKET: str = ""
    AWS_REGION: str = "eu-north-1"
    AWS_S3_ENDPOINT_URL: str = ""  # optional for S3-compatible providers
    S3_MEDIA_PUBLIC_BASE_URL: str = ""  # optional CDN/custom public object base

    # ── Channel encryption ────────────────────────────────
    CHANNEL_ENCRYPTION_KEY: str = ""  # Falls back to JWT_SECRET if empty

    # ── Email (Resend) ────────────────────────────────────────
    # Server-side only. Never expose this to the frontend.
    RESEND_API_KEY: str = ""
    RESEND_URL: str = "https://api.resend.com/emails"
    RESEND_FROM: str = "Sayvors <noreply@sayvors.com>"
    EMAIL_FROM: str = "noreply@sayvors.com"
    # Generic /email/send is restricted to the platform sending domain unless
    # this is explicitly enabled (self-hosted relay use only).
    EMAIL_SEND_ALLOW_ANY_RECIPIENT: bool = False
    FRONTEND_URL: str = "http://localhost:3000"

    # Set by the test suite (conftest). Gates the rate-limit/LLM test bypasses
    # so prod code paths can never be disarmed by an import accident.
    TESTING: bool = False

    # Live-database sources in RAG databanks normally must resolve to globally
    # routable IPs (SSRF guard). Enable ONLY for self-hosted deployments that
    # must reach private/VPN networks.
    RAG_DB_ALLOW_PRIVATE_HOSTS: bool = False

    # ── Google Business Profile (Reviews) ────────────────
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REVIEWS_POLL_INTERVAL_SECONDS: int = 300  # 5 min
    GOOGLE_REVIEWS_REDIRECT_URI: str = "http://localhost:8000/api/v1/channels/google/callback"
    # Dev/test mode for Google Reviews: fabricate sample reviews.
    GOOGLE_REVIEWS_MOCK: bool = False

    # ── Analytics / business intelligence ────────────────────────────────
    # How often the Google Business Profile performance sync runs (impressions,
    # website clicks, calls, direction requests -> location_daily_metrics).
    ANALYTICS_PERFORMANCE_SYNC_INTERVAL_SECONDS: int = 6 * 3600
    # How many days of daily metrics to pull per sync pass.
    ANALYTICS_PERFORMANCE_DAYS_BACK: int = 30
    # How often the messaging rollup worker recomputes channel_daily_metrics
    # (message volume + response health per WhatsApp/IG/FB channel). Fresh
    # enough that the unanswered snapshot reads as "now", cheap enough to
    # never matter.
    MESSAGING_ROLLUP_INTERVAL_SECONDS: int = 900
    CONVERSATION_INSIGHTS_INTERVAL_SECONDS: int = 86400  # daily
    MARKET_BENCHMARKS_INTERVAL_SECONDS: int = 86400  # daily
    FOLLOWER_SNAPSHOT_INTERVAL_SECONDS: int = 86400  # daily

    # ── LLM ────────────────────────────────────────────
    # Provider keys live exclusively in the database (Admin → LLMs).
    # No LLM keys are read from the environment.

    # ── Speech-to-text (Faster-Whisper / CTranslate2) ──────────────────
    # General-purpose speech transcription: any audio URL from any channel
    # (WhatsApp voice notes, Instagram voice messages, Facebook voice notes,
    # Telegram voice messages, Google voice posts, user uploads, etc.).
    # Not hardcoded to any platform — any caller can enqueue an STT job.
    STT_MODEL: str = "base"              # tiny, base, small, medium, large-v1, large-v2, large-v3
    STT_DEVICE: str = "cpu"              # cpu | cuda | auto
    STT_COMPUTE_TYPE: str = "int8"       # int8 | int8_float16 | float16 | float32 (device dependent)
    STT_BEAM_SIZE: int = 5
    STT_VAD_FILTER: bool = True          # voice activity detection: skips silent segments
    STT_MAX_FILE_MB: int = 100           # max audio file size for transcription

    # ── Localith (EmbedSocial) ──────────────────────────────
    LOCALITH_API_KEY: str = ""
    LOCALITH_BASE_URL: str = "https://embedsocial.com/app/api"
    LOCALITH_ITEMS_PATH: str = "rest/v1/items"
    BUSINESS_DATA_PROVIDER: str = "localith"
    # Background auto-sync: every connected listing is re-synced on this
    # cadence (profile + reviews + metrics). Manual "Sync now" still works.
    LOCALITH_SYNC_INTERVAL_SECONDS: int = 300  # 5 min (reviews don't need 60s SLA)
    # Scheduled-post publisher: how often due posts are pushed to Google.
    POSTS_PUBLISH_INTERVAL_SECONDS: int = 300  # 5 min
    # Scheduled-media publisher: how often due photos go live on Google.
    MEDIA_PUBLISH_INTERVAL_SECONDS: int = 300  # 5 min

    # ── Platform admin (separate password, no user record) ──────
    # Bcrypt hash of the admin password. Empty = admin API disabled.
    # Generate: python -c "import bcrypt; print(bcrypt.hashpw(b'PW', bcrypt.gensalt()).decode())"
    # -- Meta integrations (WhatsApp / Facebook / Instagram) --
    # Platform-level app credentials (same precedent as Google OAuth:
    # app-owned env, per-tenant tokens encrypted in the database).
    # Never expose these to the frontend.
    META_APP_ID: str = ""
    META_APP_SECRET: str = ""
    # Dedicated user-login app (Continue with Facebook). Empty = fall back to
    # the platform META_APP_ID/SECRET (same values for now; split later by env only).
    META_LOGIN_APP_ID: str = ""
    META_LOGIN_APP_SECRET: str = ""

    # Lead escalation knobs (threshold, resume window, reminder window,
    # recipients) are deliberately NOT here -- they are per-tenant, edited by
    # the owner in lead_settings and clamped by
    # lead_engine.normalize_lead_settings.

    @property
    def facebook_login_app_id(self) -> str:
        return self.META_LOGIN_APP_ID or self.META_APP_ID

    @property
    def facebook_login_app_secret(self) -> str:
        return self.META_LOGIN_APP_SECRET or self.META_APP_SECRET
    META_GRAPH_API_VERSION: str = "v26.0"
    META_OAUTH_REDIRECT_URI: str = "http://localhost:8000/api/v1/meta/facebook/callback"
    META_WEBHOOK_VERIFY_TOKEN: str = ""
    # Embedded Signup v4 Builder configuration id (App Dashboard ->
    # WhatsApp -> Embedded Signup Builder). Frontend passes it to FB.login.
    META_WHATSAPP_CONFIG_ID: str = ""
    # Separate Builder configuration for WhatsApp Coexistence ("Connect
    # existing" — the customer keeps their number and their own WhatsApp
    # Business App). Meta scopes the two flows to different configurations,
    # so they cannot share one config_id. Empty = fall back to
    # META_WHATSAPP_CONFIG_ID, which is only correct if Meta has since
    # merged the flows — otherwise coexistence silently opens the standard
    # (new-number) onboarding and the merchant never sees their app.
    META_WHATSAPP_COEXISTENCE_CONFIG_ID: str = ""
    # Tech Provider solution id (Tech Provider Portal -> Solutions). When
    # set, the frontend uses the v4 app_only_install FB.login extras.
    META_SOLUTION_ID: str = ""
    # Facebook Login for Business configuration id (dashboard configuration
    # with token type + assets + permissions). Used to build the dialog URL.
    META_FACEBOOK_CONFIG_ID: str = ""
    META_INSTAGRAM_CONFIG_ID: str = ""
    # Sayvors tenant messaging quota per calendar month, keyed by users.plan.
    # This is OUR quota surfaced in the UI — never Meta's messaging tier, which
    # stays invisible to tenants on purpose.
    PLAN_MESSAGE_LIMITS: dict[str, int] = {"free": 1000, "pro": 25000}

    ADMIN_PASSWORD_HASH: str = ""
    ADMIN_SESSION_MINUTES: int = 120
    # Global (IP-independent) consecutive-failure lockout for the admin login,
    # so per-IP rate limits are not the only brute-force control.
    ADMIN_MAX_CONSECUTIVE_FAILURES: int = 10
    # httpOnly cookie the admin login sets; sessionStorage must never hold
    # the admin token (XSS-readable storage).
    ADMIN_COOKIE_NAME: str = "sayvors_admin_token"

    model_config = {"env_file": ".env"}


settings = Settings()

if settings.JWT_SECRET == "change-me-in-production":
    import sys
    print("FATAL: JWT_SECRET must be set to a strong random value in .env", file=sys.stderr)
    print("  Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(64))\"", file=sys.stderr)
    sys.exit(1)


def validate_production_settings() -> None:
    """Fail-closed startup gate for ENVIRONMENT=production.

    Dev-tolerant defaults become boot-time fatal errors in production, so a
    half-configured deploy can never serve traffic insecurely by accident.
    """
    import sys

    errors: list[str] = []
    if len(settings.JWT_SECRET) < 32:
        errors.append("JWT_SECRET must be >= 32 chars (looks like a placeholder)")
    if not settings.CHANNEL_ENCRYPTION_KEY:
        errors.append(
            "CHANNEL_ENCRYPTION_KEY must be set explicitly "
            "(the JWT_SECRET fallback is not acceptable for stored channel tokens)"
        )
    if not settings.ADMIN_PASSWORD_HASH:
        errors.append("ADMIN_PASSWORD_HASH must be set (admin panel must be intentional)")
    if not settings.ALLOWED_HOSTS or "*" in settings.ALLOWED_HOSTS:
        errors.append("ALLOWED_HOSTS must list explicit production hosts (no wildcard)")
    if not settings.CORS_ORIGINS or any("localhost" in o for o in settings.CORS_ORIGINS):
        errors.append("CORS_ORIGINS must list the real frontend origin(s), not localhost")
    if settings.CORS_ORIGIN_REGEX and "localhost" in settings.CORS_ORIGIN_REGEX:
        errors.append("CORS_ORIGIN_REGEX must not reference localhost in production")
    if "localhost" in settings.FRONTEND_URL:
        errors.append("FRONTEND_URL must not reference localhost in production")
    if "localhost" in settings.GOOGLE_REVIEWS_REDIRECT_URI:
        errors.append("GOOGLE_REVIEWS_REDIRECT_URI must not reference localhost in production")
    if "localhost" in settings.META_OAUTH_REDIRECT_URI:
        errors.append("META_OAUTH_REDIRECT_URI must not reference localhost in production")
    if settings.EMAIL_SEND_ALLOW_ANY_RECIPIENT:
        errors.append("EMAIL_SEND_ALLOW_ANY_RECIPIENT must stay off (open-relay guard)")
    if settings.RAG_DB_ALLOW_PRIVATE_HOSTS:
        errors.append("RAG_DB_ALLOW_PRIVATE_HOSTS must stay off (SSRF guard)")
    if errors:
        print("FATAL: production configuration validation failed:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)


if settings.ENVIRONMENT == "production":
    validate_production_settings()
