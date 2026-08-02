from pydantic import BaseModel, Field


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    voice_id: str | None = None
    language: str = "en"
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


class TTSJobResponse(BaseModel):
    id: str
    status: str
    audio_url: str | None = None
    duration_ms: int | None = None
    error: str | None = None
    created_at: str


class VoiceResponse(BaseModel):
    id: str
    name: str
    provider: str
    language: str
    gender: str | None = None
    preview_url: str | None = None


class TTSJobListResponse(BaseModel):
    jobs: list[TTSJobResponse]
    total: int
