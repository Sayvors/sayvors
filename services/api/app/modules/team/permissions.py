"""Permission catalog for team RBAC — the single source of truth.

One permission string per capability, "{area}.{action}". The same catalog
drives: seeded role templates, the role-builder UI (via GET /team/permissions),
and request enforcement (`require_perm`). Adding a capability here makes it
available everywhere; removing one revokes it from every role that lists it.
"""

# Ordered for UI display: area label → actions (ordered least→most privilege).
PERMISSION_CATALOG: dict[str, list[str]] = {
    "inbox": ["view", "reply"],
    "channels": ["view", "connect", "edit", "remove"],
    "reviews": ["view", "reply", "publish"],
    "posts": ["view", "create", "publish"],
    "analytics": ["view"],
    "media": ["view", "manage"],
    "ai": ["view", "edit"],
    "locations": ["view", "manage"],
    "databank": ["view", "manage"],
    "notifications": ["view"],
    "team": ["view", "manage"],
    "billing": ["view", "manage"],
    "settings": ["view", "edit"],
}

AREA_LABELS: dict[str, str] = {
    "inbox": "Inbox (conversations)",
    "channels": "Channels (WhatsApp, Facebook, Instagram, Google)",
    "reviews": "Reviews",
    "posts": "Posts & scheduling",
    "analytics": "Analytics",
    "media": "Media library",
    "ai": "AI & autopilot",
    "locations": "Locations",
    "databank": "Databank",
    "notifications": "Notifications",
    "team": "Team management",
    "billing": "Billing & plan",
    "settings": "Workspace settings",
}

ACTION_LABELS: dict[str, str] = {
    "view": "View",
    "reply": "Reply",
    "connect": "Connect",
    "edit": "Edit",
    "remove": "Remove",
    "create": "Create",
    "publish": "Publish",
    "manage": "Manage",
}

ALL_PERMISSIONS: list[str] = [
    f"{area}.{action}" for area, actions in PERMISSION_CATALOG.items() for action in actions
]


def is_valid_permission(perm: str) -> bool:
    area, _, action = perm.partition(".")
    return action in PERMISSION_CATALOG.get(area, ())


# ── Seeded role templates (is_system=True; permissions admin-editable) ──
# Owner is implicit — the workspace creator always has every permission
# and is never stored as a membership row.

ROLE_TEMPLATES: dict[str, list[str]] = {
    "Admin": [
        p for p in ALL_PERMISSIONS
        if not p.startswith("billing.") and p != "team.manage"
    ],
    "Agent": [
        "inbox.view", "inbox.reply",
        "channels.view",
        "reviews.view", "reviews.reply",
        "posts.view",
        "analytics.view",
        "media.view",
        "ai.view",
        "locations.view",
        "notifications.view",
        "team.view",
    ],
    "Viewer": [
        "inbox.view",
        "channels.view",
        "reviews.view",
        "posts.view",
        "analytics.view",
        "media.view",
        "locations.view",
        "notifications.view",
        "team.view",
    ],
}

SYSTEM_ROLE_NAMES = list(ROLE_TEMPLATES.keys())


def validate_role_permissions(permissions: list[str]) -> list[str]:
    """Return the deduped subset of `permissions` that exist in the catalog.
    Unknown strings are dropped silently — the catalog may shrink between
    versions and roles must never break on stale entries."""
    return [p for p in ALL_PERMISSIONS if p in set(permissions)]
