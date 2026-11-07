"""The dashboard pages the assistant may link to.

The model can only reference a real route: a hallucinated link is a dead end
for the owner. Keep this list in sync with `apps/web/app/dashboard/**` — a
page that is not here cannot be linked.
"""
from __future__ import annotations

# (label, path, what lives there)
DASHBOARD_PAGES: tuple[tuple[str, str, str], ...] = (
    ("Overview", "/dashboard", "home summary of the business"),
    ("Inbox", "/dashboard/inbox", "customer conversations across WhatsApp, Instagram, Facebook"),
    ("Reviews", "/dashboard/reviews", "Google reviews list and replies"),
    ("Review issues", "/dashboard/reviews/issues", "reviews that need attention or a reply"),
    ("Review playground", "/dashboard/reviews/playground", "test AI reply styles before using them"),
    ("Analytics", "/dashboard/analytics", "ratings, trends, locations and Google performance charts"),
    ("Insights", "/dashboard/insights", "AI findings and recommendations"),
    ("Customers", "/dashboard/customers", "people who reviewed or messaged the business"),
    ("Locations", "/dashboard/locations", "connected Google Business locations, add a location"),
    ("Verification", "/dashboard/verification", "Google Business verification status and steps"),
    ("Channels", "/dashboard/channels", "connect and manage WhatsApp, Google, Instagram, Facebook"),
    ("WhatsApp", "/dashboard/channels/whatsapp", "WhatsApp connection and settings"),
    ("WhatsApp templates", "/dashboard/channels/whatsapp/templates", "message templates for WhatsApp"),
    ("WhatsApp catalog", "/dashboard/channels/whatsapp/catalog", "product catalog for WhatsApp"),
    ("Instagram", "/dashboard/channels/instagram", "Instagram connection"),
    ("Facebook", "/dashboard/channels/facebook", "Facebook connection"),
    ("Publish", "/dashboard/publish", "write and schedule a social post"),
    ("Posts", "/dashboard/posts", "published and scheduled posts"),
    ("Media", "/dashboard/media", "photos and media library"),
    ("Automations", "/dashboard/automations", "rules that reply or notify automatically"),
    ("Leads", "/dashboard/leads", "sales leads and pipeline"),
    ("Growth", "/dashboard/growth", "growth tools and review requests"),
    ("Benchmark", "/dashboard/benchmark", "compare against competitors"),
    ("Services", "/dashboard/services", "services offered to customers"),
    ("Team", "/dashboard/team", "invite people, roles and permissions"),
    ("Plans", "/dashboard/plans", "current plan and available plans"),
    ("Billing", "/dashboard/billing", "billing details"),
    ("AI credit", "/dashboard/billing/credit", "AI credit balance and spend history"),
    ("Usage", "/dashboard/usage", "per-day AI and message usage"),
    ("Databank", "/dashboard/databank", "uploaded files and connected databases"),
    ("Memory", "/dashboard/memory", "what the assistant remembers"),
    ("Templates", "/dashboard/templates", "reply templates"),
    ("Notifications", "/dashboard/notifications", "notifications and alerts"),
    ("Outbox", "/dashboard/outbox", "scheduled and sending messages"),
    ("Profile", "/dashboard/profile", "owner profile and business details"),
    ("Settings", "/dashboard/settings", "workspace settings and preferences"),
)

_ALLOWED_PATHS = {path for _, path, _ in DASHBOARD_PAGES}


def navigation_prompt_block() -> str:
    lines = "\n".join(
        f"- {label} -> {path} ({purpose})" for label, path, purpose in DASHBOARD_PAGES
    )
    return (
        "\n\nDASHBOARD PAGES (the only valid links — never invent a path):\n"
        f"{lines}"
    )


def is_dashboard_path(path: str) -> bool:
    """True for an exact known page or a sub-tab of a known page."""
    clean = (path or "").split("?", 1)[0].split("#", 1)[0].rstrip("/")
    if clean in _ALLOWED_PATHS:
        return True
    # "/dashboard" is a prefix of every page, so it cannot license unknown
    # children; deeper known pages can (e.g. /dashboard/channels/whatsapp/settings).
    return any(
        known != "/dashboard" and clean.startswith(f"{known}/")
        for known in _ALLOWED_PATHS
    )
