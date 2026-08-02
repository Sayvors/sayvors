from pydantic import BaseModel, Field


class STTRequest(BaseModel):
    audio_url: str = Field(..., max_length=1000)
    language: str = "en"


class STTJobResponse(BaseModel):
    id: str
    status: str
    text: str | None = None
    confidence: float | None = None
    duration_ms: int | None = None
    error: str | None = None
    created_at: str


class STTJobListResponse(BaseModel):
    jobs: list[STTJobResponse]
    total: int
