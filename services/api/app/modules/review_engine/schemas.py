from pydantic import BaseModel, Field


class ReviewAnalysis(BaseModel):
    sentiment: str = Field(..., pattern="^(very_negative|negative|neutral|positive|very_positive)$")
    emotion: str = Field(..., min_length=1, max_length=40)
    intent: list[str] = Field(default_factory=list, max_length=5)
    issue_type: str | None = Field(default=None, max_length=80)
    product_reference: str | None = Field(default=None, max_length=200)
    urgency: str = Field(default="low", pattern="^(low|medium|high|critical)$")
    customer_request: str | None = Field(default=None, max_length=200)
    language: str = Field(default="en", max_length=5)


class StrategyMatch(BaseModel):
    strategy_id: str
    name: str
    reason: str = Field(..., min_length=1, max_length=200)
    priority: int = Field(default=50, ge=0, le=100)
    conditional: bool = False
    condition_note: str | None = Field(default=None, max_length=300)


class SuppressedStrategy(BaseModel):
    strategy_id: str
    name: str
    reason: str = Field(..., min_length=1, max_length=300)


class ExtractedIssue(BaseModel):
    key: str = Field(..., max_length=60)
    label: str = Field(..., max_length=120)
    detail: str = Field(..., max_length=300)
    keywords: list[str] = Field(default_factory=list, max_length=12)
    # Generic = inferred from issue_type/product_reference, not pattern-matched
    # from the text. Generic issues guide generation but never block approval alone.
    generic: bool = False
    # Natural customer-facing equivalents. Coverage accepts THESE — the reply
    # must never contain the internal key/label to satisfy validation.
    semantic: list[str] = Field(default_factory=list, max_length=12)


class StrategyFulfillment(BaseModel):
    strategy_id: str
    strategy: str = ""
    status: str = Field(default="pass", pattern="^(pass|fail)$")
    reason: str = ""
    evidence: str = ""


class ClaimVerdict(BaseModel):
    claim: str = Field(..., max_length=300)
    kind: str = Field(default="", max_length=40)
    status: str = Field(default="UNSUPPORTED", pattern="^(GROUNDED|UNSUPPORTED)$")
    source: str = Field(default="NONE", max_length=200)


class RelevanceVerdict(BaseModel):
    verdict: str = Field(default="uncertain", pattern="^(on_topic|off_topic|uncertain)$")
    reason: str = ""
    evidence: str = ""
    matched_terms: list[str] = Field(default_factory=list)


class ToolCall(BaseModel):
    tool: str
    args: dict = Field(default_factory=dict)
    result_summary: str = Field(default="", max_length=500)


class GeneratedResponse(BaseModel):
    response_text: str = Field(..., min_length=1, max_length=2000)
    strategies_used: list[str] = Field(default_factory=list)
    tools_called: list[ToolCall] = Field(default_factory=list)


class ValidationResult(BaseModel):
    passed: bool
    checks: dict[str, bool] = Field(default_factory=dict)
    issues: list[str] = Field(default_factory=list)
    regenerated: bool = False
    strategy_fulfillment: list[StrategyFulfillment] = Field(default_factory=list)
    claim_verdicts: list[ClaimVerdict] = Field(default_factory=list)


class ReviewEngineRequest(BaseModel):
    # Empty text allowed: star-only ratings flow through the engine with no
    # product reference (no evidence needed, strategies still apply).
    review_text: str = Field(default="", max_length=5000)
    rating: int = Field(..., ge=1, le=5)
    reviewer_name: str | None = Field(default=None, max_length=200)
    review_id: str | None = Field(default=None, max_length=120)
    channel: str = Field(default="google_review", max_length=32)
    channel_id: str | None = Field(default=None, max_length=36)
    # Optional explicit model override (catalog id, e.g. "groq:oss-120b").
    # If omitted and channel_id is set, the channel's auto-reply config model is used.
    model: str | None = Field(default=None, max_length=100)
    # Draft the merchant rejected — the generator must write something different.
    previous_draft: str | None = Field(default=None, max_length=4000)
    # Optional explicit dialect override (catalog code, e.g. "egyptian").
    # If omitted and channel_id is set, the channel's auto-reply config wins.
    dialect: str | None = Field(default=None, max_length=30)
    # Optional explicit language policy: match the review, or force en/ar.
    reply_language: str | None = Field(default=None, pattern="^(match|en|ar)$")
    # Optional explicit databank override (playground/tests): honored only
    # when the tenant owns the bank, else the channel-linked bank is used.
    databank_id: str | None = Field(default=None, max_length=36)


class ReviewEngineResponse(BaseModel):
    response_text: str
    strategies_used: list[str]
    validation: ValidationResult
    analysis: ReviewAnalysis
    model: str
    latency_ms: int
    log_id: str
    status: str = "generated"
    relevance: RelevanceVerdict | None = None


class ReviewStrategyOut(BaseModel):
    id: str
    name: str
    description: str
    category: str
    priority: int
    enabled: bool


class ReviewStrategyUpdate(BaseModel):
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=100)
    instructions: list[str] | None = None
