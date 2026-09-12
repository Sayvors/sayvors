from dataclasses import dataclass


@dataclass
class ModelInfo:
    id: str            # catalog id: "openai:gpt-4o"
    name: str          # display name: "GPT-4o"
    provider: str      # provider key: "openai"
    api_model: str     # actual model name sent to provider: "gpt-4o"
    context: int       # context window in tokens
    max_output: int    # max output tokens
    supports_stream: bool = True


MODELS: list[ModelInfo] = [
    # ── OpenAI ──────────────────────────────────────────
    ModelInfo("openai:gpt-4o", "GPT-4o", "openai", "gpt-4o", 128_000, 16_384),
    ModelInfo("openai:gpt-4o-mini", "GPT-4o Mini", "openai", "gpt-4o-mini", 128_000, 16_384),
    ModelInfo("openai:gpt-4-turbo", "GPT-4 Turbo", "openai", "gpt-4-turbo", 128_000, 4_096),
    ModelInfo("openai:o3-mini", "o3-mini", "openai", "o3-mini", 200_000, 100_000),
    ModelInfo("openai:o4-mini", "o4-mini", "openai", "o4-mini", 200_000, 100_000),
    # ── Grok (xAI) ──────────────────────────────────────
    ModelInfo("grok:grok-2", "Grok-2", "grok", "grok-2", 131_072, 4_096),
    ModelInfo("grok:grok-2-mini", "Grok-2 Mini", "grok", "grok-2-mini", 131_072, 4_096),
    ModelInfo("grok:grok-3", "Grok-3", "grok", "grok-3", 131_072, 8_192),
    ModelInfo("grok:grok-3-mini", "Grok-3 Mini", "grok", "grok-3-mini", 131_072, 8_192),
    # ── Gemini (Google) ─────────────────────────────────
    ModelInfo("gemini:gemini-3.6-flash", "Gemini 3.6 Flash", "gemini", "gemini-3.6-flash", 1_000_000, 65_536),
    ModelInfo("gemini:gemini-2.5-pro", "Gemini 2.5 Pro", "gemini", "gemini-2.5-pro", 1_000_000, 65_536),
    ModelInfo("gemini:gemini-2.5-flash", "Gemini 2.5 Flash", "gemini", "gemini-2.5-flash", 1_000_000, 65_536),
    # ── Kimi (Moonshot) ─────────────────────────────────
    ModelInfo("kimi:kimi-k2", "Kimi K2", "kimi", "kimi-k2", 128_000, 16_384),
    ModelInfo("kimi:moonshot-v1-128k", "Moonshot v1 128k", "kimi", "moonshot-v1-128k", 128_000, 4_096),
    ModelInfo("kimi:moonshot-v1-32k", "Moonshot v1 32k", "kimi", "moonshot-v1-32k", 32_768, 4_096),
    ModelInfo("kimi:moonshot-v1-8k", "Moonshot v1 8k", "kimi", "moonshot-v1-8k", 8_192, 4_096),
    # ── DeepSeek ────────────────────────────────────────
    ModelInfo("deepseek:deepseek-chat", "DeepSeek Chat", "deepseek", "deepseek-chat", 64_000, 8_192),
    ModelInfo("deepseek:deepseek-reasoner", "DeepSeek Reasoner", "deepseek", "deepseek-reasoner", 64_000, 8_192),
    # ── GroqCloud (OpenAI-compatible, free tier, no card) ──
    ModelInfo("groq:oss-120b", "GPT OSS 120B (Groq)", "groq", "openai/gpt-oss-120b", 131_072, 65_536),
    ModelInfo("groq:oss-20b", "GPT OSS 20B (Groq)", "groq", "openai/gpt-oss-20b", 131_072, 65_536),
    # ── Ollama (local) ──────────────────────────────────
    ModelInfo("ollama:llama3.1", "Llama 3.1 (local)", "ollama", "llama3.1", 128_000, 4_096),
    ModelInfo("ollama:mistral", "Mistral (local)", "ollama", "mistral", 32_000, 4_096),
    ModelInfo("ollama:qwen3", "Qwen3 (local)", "ollama", "qwen3", 32_000, 4_096),
]

PROVIDERS = ["openai", "grok", "gemini", "kimi", "deepseek", "groq", "ollama"]


def get_model_by_id(model_id: str) -> ModelInfo | None:
    for m in MODELS:
        if m.id == model_id:
            return m
    return None


def get_provider_from_model(model_id: str) -> str:
    parts = model_id.split(":", 1)
    return parts[0] if len(parts) == 2 else "openai"
