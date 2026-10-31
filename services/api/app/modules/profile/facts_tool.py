"""The AI's business-facts tool.

One tool, one argument. The model (or the deterministic router) asks for a
topic and gets the slice — hours across all locations, the website, the
services, the team — instead of the reply path stuffing every fact into the
prompt on every message.

Tenant scope is NEVER an argument: the caller passes the tenant id from the
authenticated context, so a prompt-injected argument cannot read another
tenant's facts.
"""

from __future__ import annotations

import logging
import re

from ..llm.gateway import ToolDefinition, ToolParameter
from .facts_store import render_locations

logger = logging.getLogger(__name__)

TOPICS: tuple[str, ...] = (
    "hours", "locations", "website", "contact", "services", "team", "owner", "all",
)

FACTS_TOOL = ToolDefinition(
    name="get_business_facts",
    description=(
        "Read this business's own facts. Use before answering any factual "
        "question: opening hours (per location), address/branches, website, "
        "services offered, team, owner."
    ),
    parameters={
        "topic": ToolParameter(
            type="string",
            description=(
                "One of: hours, locations, website, contact, services, team, "
                "owner, all. Use 'hours' for opening/closing times, "
                "'locations' for branches/addresses."
            ),
        )
    },
    required=["topic"],
)

_ALIASES = {
    "opening_hours": "hours",
    "opening hours": "hours",
    "working_hours": "hours",
    "schedule": "hours",
    "branches": "locations",
    "branch": "locations",
    "address": "locations",
    "addresses": "locations",
    "where": "locations",
    "site": "website",
    "url": "website",
    "links": "website",
    "email": "contact",
    "phone": "contact",
    "whatsapp": "contact",
    "menu": "services",
    "offerings": "services",
    "products": "services",
    "staff": "team",
    "employees": "team",
    "ceo": "owner",
    "founder": "owner",
    "boss": "owner",
}

# Deterministic router. Kept deliberately small: it only needs to cover the
# topics customers actually ask, and anything missed is still available to the
# model through the tool call.
_TOPIC_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("hours", re.compile(
        r"\b(hours?|open|opens?|opening|clos(e|es|ed|ing)|working\s*hours?|"
        r"what\s*time|timings?|business\s*hours?)\b|"
        r"(ساعات|الدوام|مواعيد|تفتحون|تفتح|مفتوح|مغلق)",
        re.IGNORECASE,
    )),
    ("locations", re.compile(
        r"\b(address|location|locations|where\s+are|branch(es)?|directions?|"
        r"visit|come\s+to)\b|(عنوان|موقع|مواقع|فرع|فروع|وين|أين)",
        re.IGNORECASE,
    )),
    ("website", re.compile(
        r"\b(website|site|link|url|web\s*site)\b|(موقعكم|رابط|الموقع الإلكتروني)",
        re.IGNORECASE,
    )),
    ("services", re.compile(
        r"\b(services?|offer(ed|s|ing)?|provide|menu|products?|packages?)\b|"
        r"(خدمات|خدمة|تقدمون|منتجات)",
        re.IGNORECASE,
    )),
    ("team", re.compile(
        r"\b(team|staff|employees?|who\s+(is|are|works)|ceo|founder|owner|"
        r"manager|colleague)\b|(فريق|موظف|المدير|المؤسس)",
        re.IGNORECASE,
    )),
    ("contact", re.compile(
        r"\b(email|e-mail|phone|number|contact\s+(us|details?)|call\s+you)\b|"
        r"(ايميل|بريد|هاتف|رقم|اتصال)",
        re.IGNORECASE,
    )),
)


def detect_topics(text: str | None) -> list[str]:
    """Topics a message asks about, in priority order (hours first)."""
    if not text:
        return []
    hits: list[str] = []
    for topic, pattern in _TOPIC_PATTERNS:
        if pattern.search(text):
            hits.append(topic)
    # "Who is the CEO and what are your hours?" → both, but never the whole
    # encyclopedia: two slices are enough for one reply.
    return hits[:2]


def _services_text(facts: dict) -> str:
    services = facts.get("services") or {}
    offered = services.get("offered") or []
    not_offered = services.get("not_offered") or []
    lines: list[str] = []
    if offered:
        lines.append(f"Services offered: {', '.join(offered)}")
    if not_offered:
        lines.append(f"Services NOT offered: {', '.join(not_offered)}")
    return "\n".join(lines)


def _team_text(facts: dict) -> str:
    lines: list[str] = []
    owner = (facts.get("business") or {}).get("owner")
    if owner:
        lines.append(f"Owner: {owner}")
    team = facts.get("team") or []
    if team:
        members = ", ".join(
            f"{m['name']} ({m['role']})" if m.get("role") else m["name"]
            for m in team
        )
        lines.append(f"Team: {members}")
    return "\n".join(lines)


def _locations_text(facts: dict) -> str:
    locations = facts.get("locations") or []
    if not locations:
        return ""
    lines = [f"We have {len(locations)} location{'s' if len(locations) != 1 else ''}:"]
    for loc in locations:
        label = ", ".join(
            part for part in (loc.get("name"), loc.get("address")) if part
        ) or loc.get("listing_id") or "location"
        schedule = loc.get("schedule") or "hours not set"
        lines.append(f"- {label}: {schedule}")
    return "\n".join(lines)


def _website_text(facts: dict) -> str:
    contact = facts.get("contact") or {}
    sites = list(contact.get("websites") or [])
    for loc in facts.get("locations") or []:
        site = loc.get("website")
        if site and site not in sites:
            sites.append(site)
    return f"Website: {', '.join(sites[:3])}" if sites else ""


def _contact_text(facts: dict) -> str:
    contact = facts.get("contact") or {}
    lines: list[str] = []
    if contact.get("address"):
        lines.append(f"Address: {contact['address']}")
    if contact.get("email"):
        lines.append(f"Email: {contact['email']}")
    if contact.get("websites"):
        lines.append(f"Website: {', '.join(contact['websites'][:3])}")
    return "\n".join(lines)


def render_topic(facts: dict, topic: str) -> str:
    """The text for one topic. "" when the fact is not configured."""
    topic = _ALIASES.get(str(topic or "").strip().lower(), str(topic or "").strip().lower())
    if topic == "hours":
        text = render_locations(facts.get("locations") or [])
        if not text:
            return ""
        return (
            "OPENING HOURS (the business's physical visiting hours — not the "
            "assistant's availability; the assistant answers 24/7):\n" + text
        )
    if topic == "locations":
        return _locations_text(facts)
    if topic == "website":
        return _website_text(facts)
    if topic == "contact":
        return _contact_text(facts)
    if topic == "services":
        return _services_text(facts)
    if topic == "team":
        return _team_text(facts)
    if topic == "owner":
        owner = (facts.get("business") or {}).get("owner")
        return f"Owner: {owner}" if owner else ""
    if topic == "all":
        parts = [
            _contact_text(facts),
            _services_text(facts),
            _team_text(facts),
            render_topic(facts, "hours"),
        ]
        return "\n".join(part for part in parts if part)
    return ""


async def run_facts_tool(db, tenant_id: str, topic: str) -> str:
    """Execute the tool for one topic, tenant-scoped by the caller."""
    from .facts_store import get_facts

    facts = await get_facts(db, tenant_id)
    return render_topic(facts, topic)
