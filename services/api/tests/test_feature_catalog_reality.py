"""Feature-catalog reality checks (§34).

The catalog must only contain features with actual product/backend meaning —
no phantom entries (SLA, priority support, AI search, ASK Sayvors premium)
that would surface as confusing checkboxes in the admin tenant modal and the
tenant plans page.
"""
from app.modules.billing.features import FEATURE_CATALOG, FEATURE_KEYS

PHANTOM_KEYS = {"sla", "priority_support", "ai_search", "ask_sayvors_premium"}

# Every real feature key we ship (keep in sync with the migration).
REAL_KEYS = {
    "channels", "messaging", "ai_replies", "posts", "media", "reviews",
    "analytics", "automation", "databank", "leads", "voice", "scheduling",
    "assistant", "social_response_style", "bulk_edit_csv", "benchmarking",
    "benchmark_external", "verifications", "growth", "ticket_assignment",
    "voice_replies",
}


def test_catalog_has_no_phantom_features():
    assert PHANTOM_KEYS.isdisjoint(FEATURE_KEYS)


def test_catalog_covers_all_real_features():
    assert REAL_KEYS <= FEATURE_KEYS
    # No extras beyond the documented set.
    assert FEATURE_KEYS == REAL_KEYS


def test_catalog_entries_are_unique_and_labeled():
    labels = [f.label for f in FEATURE_CATALOG]
    assert len(labels) == len(set(labels))
    assert all(f.key and f.label for f in FEATURE_CATALOG)
