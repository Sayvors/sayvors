from pydantic import BaseModel, Field


class FeedbackCreate(BaseModel):
    emoji_rating: int = Field(..., ge=1, le=5)
    message: str | None = Field(None, max_length=2000)


class FeedbackOut(BaseModel):
    id: str
    user_id: str
    emoji_rating: int
    message: str | None = None
    created_at: str | None = None


class FeedbackList(BaseModel):
    total: int
    items: list[FeedbackOut]
