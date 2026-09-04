from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/sayvors"
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
    ALLOWED_HOSTS: list[str] = ["localhost", "127.0.0.1"]

    # ── File uploads ────────────────────────────────────
    UPLOAD_DIR: str = "./data/uploads"
    MAX_UPLOAD_SIZE_MB: int = 100

    # ── Channel encryption ────────────────────────────────
    CHANNEL_ENCRYPTION_KEY: str = ""  # Falls back to JWT_SECRET if empty

    # ── Email ────────────────────────────────────────────
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
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
    # Demo environment: show seeded data regardless of the logged-in user.
    DEMO_MODE: bool = False

    # ── Analytics / business intelligence ────────────────────────────────
    # How often the Google Business Profile performance sync runs (impressions,
    # website clicks, calls, direction requests -> location_daily_metrics).
    ANALYTICS_PERFORMANCE_SYNC_INTERVAL_SECONDS: int = 6 * 3600
    # How many days of daily metrics to pull per sync pass.
    ANALYTICS_PERFORMANCE_DAYS_BACK: int = 30

    # ── LLM provider API keys ──────────────────────────
    OPENAI_API_KEY: str = ""
    XAI_API_KEY: str = ""           # Grok
    MOONSHOT_API_KEY: str = ""      # Kimi
    DEEPSEEK_API_KEY: str = ""
    GEMINI_API_KEY: str = ""        # Google Gemini
    OLLAMA_API_KEY: str = ""        # local Ollama (optional)

    model_config = {"env_file": ".env"}


settings = Settings()

if settings.JWT_SECRET == "change-me-in-production":
    import sys
    print("FATAL: JWT_SECRET must be set to a strong random value in .env", file=sys.stderr)
    print("  Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(64))\"", file=sys.stderr)
    sys.exit(1)
