"""Request and response contracts for the tenant-scoped prompt library."""
from pydantic import BaseModel, Field, field_validator, model_validator


def _strip_text(value: object) -> object:
    return value.strip() if isinstance(value, str) else value


class PromptIn(BaseModel):
    channel_id: str = Field(min_length=1, max_length=36)
    title: str = Field(min_length=1, max_length=200)
    prompt_text: str = Field(min_length=3, max_length=1000)
    intent: str = Field(default="custom", max_length=80)

    @field_validator("title", "prompt_text", "intent", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return _strip_text(value)


class PromptPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    prompt_text: str | None = Field(default=None, min_length=3, max_length=1000)
    intent: str | None = Field(default=None, max_length=80)
    is_active: bool | None = None

    @field_validator("title", "prompt_text", "intent", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return _strip_text(value)

    @model_validator(mode="after")
    def reject_explicit_nulls(self) -> "PromptPatch":
        """PATCH omission leaves a field alone; an explicit null is invalid."""
        if any(getattr(self, name) is None for name in self.model_fields_set):
            raise ValueError("null_patch_value")
        return self


class PromptOut(BaseModel):
    id: str
    channel_id: str
    title: str
    prompt_text: str
    intent: str
    is_active: bool
    created_at: str
    updated_at: str


class PromptListOut(BaseModel):
    items: list[PromptOut]


class RunIn(BaseModel):
    channel_id: str = Field(min_length=1, max_length=36)
    prompt_id: str = Field(min_length=1, max_length=36)


class RunOut(BaseModel):
    id: str
    channel_id: str
    prompt_id: str
    prompt_snapshot: str
    locale: str
    status: str
    job_id: str | None
    validation_status: str
    error: str | None
    created_at: str
    updated_at: str
