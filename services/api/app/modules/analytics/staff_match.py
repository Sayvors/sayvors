"""Name normalization + matching for staff mentions.

The customer writes the name the way they heard it: "Ahmad"/"Ahmed",
"albakhair"/"Al Bakhair", in Arabic script or Latin. The matcher canonicalizes
both sides (review names and employee names/aliases) to one key so variants
collapse:

- lowercase, trim, collapse inner whitespace
- strip Arabic diacritics (tashkeel) and the tatweel elongation character
- unify alef/hamza forms (أ إ آ ٱ -> ا) and ta marbuta -> ha, alef maqsura -> ya
- strip common honorifics/prefixes ("mr", "الاستاذ"/"الأستاذ", "ustadh") so
  "Mr Ahmad" and "الأستاذ أحمد" match plain "Ahmad"/"أحمد"

This is deliberately deterministic (no LLM): the same name must always map to
the same key, or per-employee history would fragment.
"""
from __future__ import annotations

import re
import unicodedata

# Arabic diacritical marks (tashkeel) + tatweel.
_ARABIC_MARKS = re.compile(r"[\u064B-\u065F\u0670\u0640]")
# Alef variants unify to plain alef.
_ALEF_VARIANTS = re.compile(r"[\u0623\u0625\u0622\u0671]")
# Ta marbuta -> ha; alef maqsura -> ya (both common in names).
_TA_MARBUTA = "\u0629"
_ALEF_MAQSURA = "\u0649"
# Honorifics/prefixes that add nothing to identity (Latin + Arabic).
_HONORIFICS = {
    "mr", "mr.", "mrs", "mrs.", "ms", "ms.", "dr", "dr.",
    "ustadh", "ustaz", "الاستاذ", "الأستاذ", "استاذ", "استاز",
}

_MAX_NAME_LEN = 120


def normalize_staff_name(raw: str | None) -> str:
    """The canonical key for one person-name, or "" when nothing usable."""
    if not raw or not isinstance(raw, str):
        return ""
    text = unicodedata.normalize("NFKC", raw).strip().lower()
    # Fold Latin accented letters to ASCII (é -> e) before other work.
    text = "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )
    text = _ARABIC_MARKS.sub("", text)
    text = _ALEF_VARIANTS.sub("\u0627", text)
    text = text.replace(_TA_MARBUTA, "\u0647").replace(_ALEF_MAQSURA, "\u064A")
    # Tokens left after dropping honorifics; a name that is ONLY an honorific
    # normalizes to "" (nothing usable).
    tokens = [
        t for t in re.split(r"[\s.\-_]+", text)
        if t and t not in _HONORIFICS
    ]
    key = " ".join(tokens)
    return key[:_MAX_NAME_LEN]


def match_staff_names(
    extracted: list[dict],
    employees: list,
) -> list[dict]:
    """Attach staff_member_id to each extracted mention where one matches.

    `extracted` is the enrichment's staff list: [{"name": ..., "sentiment":
    ...}]. `employees` is the tenant's StaffMember rows (active ones). Returns
    the same list with two added keys per entry: `staff_member_id` (None when
    unmatched — the unassigned bucket) and `name_normalized`.

    First name wins: an employee whose name OR any alias normalizes to the
    extracted key. When two employees share a normalized key (data error the
    unique index prevents per listing), the first match is used — deterministic
    because the caller passes employees in stable order.
    """
    if not extracted:
        return []
    index: dict[str, object] = {}
    for emp in employees or []:
        keys = [getattr(emp, "normalized_name", "")]
        for alias in getattr(emp, "aliases", None) or []:
            keys.append(normalize_staff_name(str(alias)))
        for key in keys:
            if key and key not in index:
                index[key] = emp

    out: list[dict] = []
    for item in extracted:
        if not isinstance(item, dict):
            continue
        display = str(item.get("name") or "").strip()
        if not display:
            continue
        key = normalize_staff_name(display)
        emp = index.get(key) if key else None
        out.append({
            "name": display,
            "sentiment": str(item.get("sentiment") or "neutral"),
            "name_normalized": key,
            "staff_member_id": getattr(emp, "id", None) if emp else None,
        })
    return out
