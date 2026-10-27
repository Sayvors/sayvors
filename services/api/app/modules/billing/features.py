"""Canonical feature catalog for plan entitlements.

A single source of truth for the set of feature keys an admin can toggle
per plan. The admin UI renders one checkbox per entry here; the backend
enforces the resulting booleans via entitlements.has_feature().

Adding a feature: add an entry below + enforce it at the relevant write
path. Removing one: delete the entry; old plans simply keep a stale true
that no code reads (harmless).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureSpec:
    key: str
    label: str
    description: str
    # Whether the feature is on by default for a brand-new plan.
    default: bool = False


FEATURE_CATALOG: list[FeatureSpec] = [
    FeatureSpec("channels", "Channels", "Connect messaging channels (WhatsApp, Instagram, Facebook, Google).", True),
    FeatureSpec("messaging", "Messaging", "Send outbound messages in the inbox.", True),
    FeatureSpec("ai_replies", "AI replies", "AI-generated review replies and agent completions.", True),
    FeatureSpec("reviews", "Reviews", "Review management and auto-reply.", True),
    FeatureSpec("posts", "Posts", "Social media post publishing.", True),
    FeatureSpec("media", "Media", "Media library and uploads.", True),
    FeatureSpec("analytics", "Analytics", "Analytics dashboards and reports.", False),
    FeatureSpec("automation", "Automation", "Automation rules and triggers.", False),
    FeatureSpec("databank", "Knowledge base", "Databank / RAG knowledge base.", False),
    FeatureSpec("leads", "Leads", "Lead management and pipeline.", False),
    FeatureSpec("voice", "Voice", "Voice messages and TTS.", False),
    FeatureSpec("scheduling", "Scheduling", "Post scheduling.", False),
    FeatureSpec("assistant", "Assistant", "AI assistant chat.", False),
    FeatureSpec("priority_support", "Priority support", "Priority support channel.", False),
    FeatureSpec("sla", "SLA", "Service-level agreement.", False),
]

FEATURE_KEYS: set[str] = {f.key for f in FEATURE_CATALOG}


def feature_catalog_as_dicts() -> list[dict]:
    return [
        {"key": f.key, "label": f.label, "description": f.description, "default": f.default}
        for f in FEATURE_CATALOG
    ]


def default_features() -> dict[str, bool]:
    return {f.key: f.default for f in FEATURE_CATALOG}


def sanitize_features(raw: dict | None) -> dict[str, bool]:
    """Keep only known keys; coerce values to bool. Unknown keys dropped."""
    if not raw:
        return {}
    out: dict[str, bool] = {}
    for k, v in raw.items():
        if k in FEATURE_KEYS:
            out[k] = bool(v)
    return out
