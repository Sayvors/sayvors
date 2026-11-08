"""Request schemas shared by the newsletter campaign API and service."""
from pydantic import BaseModel, Field


class CampaignCreateIn(BaseModel):
    subject: str = Field(..., min_length=1, max_length=200)
    html: str = Field(..., min_length=1, max_length=200_000)
    text: str | None = Field(None, max_length=200_000)
    batch_size: int = Field(500, ge=50, le=2000)
    interval_seconds: int = Field(60, ge=10, le=3600)
