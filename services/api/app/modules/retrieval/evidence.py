"""Evidence contracts for the Retrieval Layer.

The Strategy Engine declares WHAT evidence a strategy needs (EvidenceNeed).
The Retrieval Layer decides HOW to obtain it and returns the minimum
relevant facts (EvidenceResult). The generation LLM only ever sees rendered
facts — never which mechanism (CSV, vector, keyword, live DB) produced them.

Provenance (mechanism + origin) stays on the Evidence objects for server
logs and debugging; it is never rendered into prompts.
"""
from dataclasses import dataclass, field

# Evidence kinds the engine can request.
NEED_PRODUCT = "product"
NEED_OFFER = "offer"
NEED_BUSINESS_PROFILE = "business_profile"
NEED_BUSINESS_OVERVIEW = "business_overview"

NEED_KINDS = (NEED_PRODUCT, NEED_OFFER, NEED_BUSINESS_PROFILE, NEED_BUSINESS_OVERVIEW)

# Maximum facts returned per need — the "minimum relevant evidence" rule.
# A strategy gets what it needs to execute, not the whole databank.
NEED_BUDGETS = {
    NEED_PRODUCT: 3,
    NEED_OFFER: 2,
    NEED_BUSINESS_PROFILE: 5,
    NEED_BUSINESS_OVERVIEW: 6,
}

# Needs allowed to consult live external databases when the caller opts in.
# Snapshot mechanisms (structured + hybrid) always run; live is explicit.
LIVE_CAPABLE_NEEDS = (NEED_PRODUCT, NEED_OFFER)


@dataclass(frozen=True)
class EvidenceNeed:
    """One evidence requirement declared by the Strategy Engine."""

    kind: str
    query: str
    limit: int = 0  # 0 = layer budget for the kind

    def __post_init__(self):
        if self.kind not in NEED_KINDS:
            raise ValueError(f"Unknown evidence kind: {self.kind}")


@dataclass
class Evidence:
    """One retrieved fact. `mechanism`/`origin` are internal provenance —
    rendering uses `fact` only."""

    kind: str
    fact: str
    score: float = 0.0
    mechanism: str = ""
    origin: str = ""


@dataclass
class EvidenceResult:
    """Fulfilled need: minimized, de-duplicated facts plus provenance."""

    need: EvidenceNeed
    items: list[Evidence] = field(default_factory=list)

    @property
    def has_data(self) -> bool:
        return bool(self.items)

    @property
    def facts(self) -> list[str]:
        return [e.fact for e in self.items]

    @property
    def rendered(self) -> str:
        """Prompt-ready facts. No mechanism names, no origins, no labels."""
        return "\n".join(f"- {e.fact}" for e in self.items)
