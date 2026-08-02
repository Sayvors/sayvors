from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/sayvors"
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_MINUTES: int = 60 * 24
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]
    REDIS_URL: str = "redis://localhost:6379/0"
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"

    # ── LLM provider API keys ──────────────────────────
    OPENAI_API_KEY: str = ""
    XAI_API_KEY: str = ""           # Grok
    MOONSHOT_API_KEY: str = ""      # Kimi
    DEEPSEEK_API_KEY: str = ""
    GEMINI_API_KEY: str = ""        # Google Gemini
    OLLAMA_API_KEY: str = ""        # local Ollama (optional)

    model_config = {"env_file": ".env"}


settings = Settings()
