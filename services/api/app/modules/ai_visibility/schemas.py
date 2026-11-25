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


class OverviewOut(BaseModel):
    completed_runs: int
    mention_rate: float | None
    citation_rate: float | None
    recommendation_rate: float | None
    active_prompts: int
    covered_prompts: int
    prompt_coverage: float | None
    failed_runs: int
    insufficient_runs: int
    source_count: int
    validated_claim_count: int


class RunListItem(BaseModel):
    id: str
    channel_id: str
    prompt_id: str
    prompt_title: str
    status: str
    mentioned: bool | None
    cited: bool | None
    recommended: bool | None
    incorrect: bool | None
    source_count: int
    validation_status: str
    created_at: str
    completed_at: str | None


class RunListOut(BaseModel):
    items: list[RunListItem]
    total: int


class SourceOut(BaseModel):
    id: str
    position: int
    url: str
    title: str | None
    snippet: str | None
    excerpt: str | None
    fetch_error: str | None


class RunDetailOut(RunOut):
    answer_text: str | None
    mentioned: bool | None
    cited: bool | None
    recommended: bool | None
    incorrect: bool | None
    evidence_coverage: dict
    competitor_mentions: list
    claims: list
    actions: list
    sources: list[SourceOut]
    completed_at: str | None
