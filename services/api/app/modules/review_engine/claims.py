"""Factual-claim extraction + grounding against retrieved business context.

Engine-level rule: NO DATA → NO CLAIM. Every factual business assertion in
a generated reply must be traceable to retrieved Databank records, Business
Context, verified product/offer data, or another authorized source.

Tenant/business agnostic: no business names, products, prices, or facts are
hardcoded here. Extraction finds *claim shapes* (rationale, habitual action,
superlative, past action); grounding compares content cores against whatever
context was actually retrieved for THIS run.
"""
import logging
import re

logger = logging.getLogger(__name__)

# (kind, pattern) — each match on a sentence yields one candidate claim.
CLAIM_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("rationale",
     re.compile(r"\b(pric\w*|fees?|costs?)\s+(reflects?|is based on|are based on|accounts? for)\b", re.I)),
    ("rationale",
     re.compile(r"\breflects?\s+(the\s+)?(quality|value|standards?)\b", re.I)),
    ("rationale",
     re.compile(r"\bquality\b.{0,25}\b(we |our )?(provide|deliver|offer|maintain|stand behind)\b", re.I)),
    ("rationale",
     re.compile(r"\bservice standards?\b", re.I)),
    ("habitual",
     re.compile(r"\bwe('re| are)?\s+(always|constantly|continually)\s+\w+", re.I)),
    ("habitual",
     re.compile(r"\b(always|constantly)\s+(looking|working|striving|aiming)\s+to\b", re.I)),
    ("process_action",
     re.compile(r"\bwe('re| are| will|'ll)\s+(reviewing|improving|working to|ensuring|providing|delivering|maintaining|monitoring|inspecting|striving|committed to)\b", re.I)),
    ("superlative",
     re.compile(r"\b(best|finest|highest|freshest)\s+(value|quality|ingredients?|service|experience|food)\b", re.I)),
    ("past_action",
     re.compile(r"\b(team|staff|crew)\b.{0,30}\b(completed|finished|underwent)\b", re.I)),
    ("past_action",
     re.compile(r"\bwe('ve| have)\s+(launched|implemented|introduced|completed)\b", re.I)),
    ("care_claim",
     re.compile(r"\bcare deeply\b|\btruly care\b|\bmeans? (the world|everything) to us\b|\btop priority\b", re.I)),
]

# Conversational attitudes tied to THIS review — never factual claims.
# (Kept narrow: anything not listed here is judged on its shape.)
SAFE_ATTITUDES = [
    "sorry", "apologize", "apology", "thank", "thanks", "appreciate",
    "take this seriously", "taken seriously", "looking into",
    "opportunity to make", "make things right", "make it right",
    "welcome", "hope to see", "come back", "visit again",
    "reach out", "contact us", "let us know", "get in touch",
    "share more details", "understand what went wrong",
]

CLAIM_STOPWORDS = frozenset(
    "the a an and or for with was were are our your you your yours we us they their "
    "there them its it's this that have has had has will would shall can could may might "
    "must should do does did done been being all any per via from into onto upon about "
    "above after before between during under over such very really much more most than "
    "then also just don doesn isn aren wasn weren hasn haven couldn't wouldn't should "
    "here there when what which who whom how why not but so yet nor as at by of on to "
    "in is it be he she him her his hers ours yours theirs my mine me my myself "
    "take takes took make makes made give gives get gets say says said tell tells told "
    "ask asks know knows think thinks thought feel feels felt want wants like loves hope "
    "wish seem seems look looks sound sounds come came go goes went keep kept stay remain "
    "become became let lets allow allows help helps use used try tried need needs show shows "
    "find found hear heard share shared understand understood believe".split()
)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if s.strip()]


def _is_safe_attitude(sentence_lower: str) -> bool:
    """A sentence made ONLY of safe attitudes carries no factual claim."""
    words = [w for w in re.findall(r"[a-z']+", sentence_lower) if w not in CLAIM_STOPWORDS]
    if not words:
        return True
    # Safe iff every content word sits inside a safe-attitude phrase.
    covered = set()
    for phrase in SAFE_ATTITUDES:
        if phrase in sentence_lower:
            covered.update(re.findall(r"[a-z']+", phrase))
    # Content words like sorry/thank/appreciate (len>=4 cores) covered → safe.
    return all(w in covered or len(w) < 5 for w in words)


def extract_claims(response_text: str) -> list[dict]:
    """Return [{claim, kind}] — one per matched sentence (deduplicated)."""
    found: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for sent in _sentences(response_text):
        lowered = sent.lower()
        if _is_safe_attitude(lowered):
            continue
        for kind, pattern in CLAIM_PATTERNS:
            if pattern.search(sent):
                key = (sent, kind)
                if key not in seen:
                    seen.add(key)
                    found.append({"claim": sent, "kind": kind})
    return found


def _claim_cores(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]{4,}", (text or "").lower())
            if w not in CLAIM_STOPWORDS]


def _core_hit(core: str, context_lower: str, context_words: set[str]) -> bool:
    if core in context_lower:
        return True
    stem = core[:5]
    for sw in context_words:
        if len(sw) >= 4 and (sw.startswith(stem) or stem.startswith(sw[:5])):
            return True
    if len(core) >= 6:
        if any(core in sw or sw in core for sw in context_words if len(sw) >= 6):
            return True
    return False


def _best_snippet(claim_cores: list[str], context: str) -> str:
    """The retrieved chunk sharing the most cores — the evidence, if any."""
    best, best_hits = "", -1
    for chunk in re.split(r"\n+", context or ""):
        lowered = chunk.lower()
        words = set(re.findall(r"[a-z]{4,}", lowered))
        hits = sum(1 for c in claim_cores if _core_hit(c, lowered, words))
        if hits > best_hits:
            best, best_hits = chunk.strip(), hits
    return best[:160] if best_hits > 0 else ""


def ground_claims(claims: list[dict], business_context: str | None) -> list[dict]:
    """Verdict per claim: {claim, kind, status, source}.

    GROUNDED needs a third of content cores (min 2) in retrieved context.
    No context → every claim UNSUPPORTED. Generic LLM assumptions are
    never evidence.
    """
    verdicts: list[dict] = []
    context = business_context or ""
    for item in claims:
        cores = _claim_cores(item["claim"])
        if not context.strip() or not cores:
            verdicts.append({**item, "status": "UNSUPPORTED", "source": "NONE"})
            continue
        lowered = context.lower()
        words = set(re.findall(r"[a-z]{4,}", lowered))
        hits = sum(1 for c in cores if _core_hit(c, lowered, words))
        if hits >= max(2, len(cores) / 3):
            verdicts.append({**item, "status": "GROUNDED",
                             "source": _best_snippet(cores, context) or "context"})
        else:
            verdicts.append({**item, "status": "UNSUPPORTED", "source": "NONE"})
    return verdicts
