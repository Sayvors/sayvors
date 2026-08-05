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
    CSRF_COOKIE_NAME: str = "csrf_token"
    REFRESH_COOKIE_NAME: str = "refresh_token"
    REFRESH_COOKIE_MAX_AGE: int = 60 * 60 * 24 * 7  # 7 days

    # ── File uploads ────────────────────────────────────
    UPLOAD_DIR: str = "./data/uploads"
    MAX_UPLOAD_SIZE_MB: int = 100

    # ── Email ────────────────────────────────────────────
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    EMAIL_FROM: str = "noreply@sayvors.com"
    FRONTEND_URL: str = "http://localhost:3000"

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
