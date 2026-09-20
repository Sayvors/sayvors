from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/sayvors"
    # AsyncPG pool: workers hold sessions across network calls (Localith,
    # Groq), so size generously and fail fast instead of hanging forever.
    DB_POOL_SIZE: int = 50
    DB_POOL_MAX_OVERFLOW: int = 50
    DB_POOL_TIMEOUT_SECONDS: int = 30
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_EXPIRATION_MINUTES: int = 15
    JWT_REFRESH_EXPIRATION_DAYS: int = 7
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]
    REDIS_URL: str = "redis://localhost:6379/0"
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"

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
    REFRESH_COOKIE_MAX_AGE: int = 60 * 60 * 24 * 7  # 7 days
    # Parent domain shared by the SPA and the API (e.g. ".sayvors.com").
    # Lets the SPA origin read the non-httpOnly CSRF cookie for the
    # X-CSRF-Token double-submit header in split-domain deployments.
    # None = host-only cookies (local dev).
    COOKIE_DOMAIN: str | None = None
    ALLOWED_HOSTS: list[str] = ["localhost", "127.0.0.1"]

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

    # ── Channel encryption ────────────────────────────────
    CHANNEL_ENCRYPTION_KEY: str = ""  # Falls back to JWT_SECRET if empty

    # ── Email (Resend) ────────────────────────────────────────
    # Server-side only. Never expose this to the frontend.
    RESEND_API_KEY: str = ""
    RESEND_URL: str = "https://api.resend.com/emails"
    RESEND_FROM: str = "Sayvors <noreply@sayvors.com>"
    EMAIL_FROM: str = "noreply@sayvors.com"
    FRONTEND_URL: str = "http://localhost:3000"

    # ── Google Business Profile (Reviews) ────────────────
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REVIEWS_POLL_INTERVAL_SECONDS: int = 300  # 5 min
    GOOGLE_REVIEWS_REDIRECT_URI: str = "http://localhost:8000/api/v1/channels/google/callback"
    # Dev/test mode for Google Reviews: fabricate sample reviews.
    GOOGLE_REVIEWS_MOCK: bool = False
    # Demo environment: analytics endpoints show the demo user's data
    # regardless of the logged-in user (useful for presenting/test-driving).
    DEMO_MODE: bool = False

    # ── Analytics / business intelligence ────────────────────────────────
    # How often the Google Business Profile performance sync runs (impressions,
    # website clicks, calls, direction requests -> location_daily_metrics).
    ANALYTICS_PERFORMANCE_SYNC_INTERVAL_SECONDS: int = 6 * 3600
    # How many days of daily metrics to pull per sync pass.
    ANALYTICS_PERFORMANCE_DAYS_BACK: int = 30

    # ── LLM ────────────────────────────────────────────
    # Provider keys live exclusively in the database (Admin → LLMs).
    # No LLM keys are read from the environment.

    # ── Localith (EmbedSocial) ──────────────────────────────
    LOCALITH_API_KEY: str = ""
    LOCALITH_BASE_URL: str = "https://embedsocial.com/app/api"
    LOCALITH_ITEMS_PATH: str = "rest/v1/items"
    BUSINESS_DATA_PROVIDER: str = "localith"
    # Background auto-sync: every connected listing is re-synced on this
    # cadence (profile + reviews + metrics). Manual "Sync now" still works.
    LOCALITH_SYNC_INTERVAL_SECONDS: int = 60  # 1 min
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
    META_GRAPH_API_VERSION: str = "v26.0"
    META_OAUTH_REDIRECT_URI: str = "http://localhost:8000/api/v1/meta/facebook/callback"
    META_WEBHOOK_VERIFY_TOKEN: str = ""
    # Embedded Signup v4 Builder configuration id (App Dashboard ->
    # WhatsApp -> Embedded Signup Builder). Frontend passes it to FB.login.
    META_WHATSAPP_CONFIG_ID: str = ""
    # Tech Provider solution id (Tech Provider Portal -> Solutions). When
    # set, the frontend uses the v4 app_only_install FB.login extras.
    META_SOLUTION_ID: str = ""
    # Facebook Login for Business configuration id (dashboard configuration
    # with token type + assets + permissions). Used to build the dialog URL.
    META_FACEBOOK_CONFIG_ID: str = ""
    META_INSTAGRAM_CONFIG_ID: str = ""

    ADMIN_PASSWORD_HASH: str = ""
    ADMIN_SESSION_MINUTES: int = 120

    model_config = {"env_file": ".env"}


settings = Settings()

if settings.JWT_SECRET == "change-me-in-production":
    import sys
    print("FATAL: JWT_SECRET must be set to a strong random value in .env", file=sys.stderr)
    print("  Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(64))\"", file=sys.stderr)
    sys.exit(1)
