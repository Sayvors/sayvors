"""Ticket identity for WhatsApp conversations.

The lead row is the ticket record; the lead fields are the sales qualification
inside it. This module owns the small mapping between the two lifecycles so the
AI, the API and the board cannot disagree:

* ticket_status — new | open | in_progress | resolved | closed
* lead.stage   — new | qualified | follow_up | converted | lost

A support conversation has a ticket and no meaningful sales stage. A sales
conversation has both; the ticket status still drives "does a human owe this
customer a reply?".
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

# Visible nowhere; stripped before the reply is sent.
_OPEN_TICKET = re.compile(r"^\s*OPEN_TICKET\s*$", re.IGNORECASE)

_TICKET_STATUS_BY_STAGE = {
    "new": "new",
    "qualified": "open",
    "follow_up": "in_progress",
    "converted": "resolved",
    "lost": "closed",
}


def new_ticket_number() -> str:
    """A stable, human-readable ticket id. Unique per tenant by index."""
    # 16 hex chars (64 bits): 1M leads have a ~2.7e-8 birthday collision
    # chance. Ten hex chars would collide with meaningful probability at that
    # scale, and the unique index would reject the write.
    return f"WA-{uuid.uuid4().hex[:16].upper()}"


def ticket_kind_for(category: str | None, intent: str | None = None) -> str:
    """Classify the work item from the already-detected lead category."""
    cat = (category or "").lower()
    if cat == "support":
        return "whatsapp_support"
    if cat in ("wholesale", "retail", "booking", "quote"):
        return "whatsapp_sales"
    if cat == "info":
        return "whatsapp_info"
    if (intent or "").lower() in ("buying", "booking", "quote"):
        return "whatsapp_sales"
    return "whatsapp_general"


def ticket_status_for_stage(stage: str | None) -> str:
    return _TICKET_STATUS_BY_STAGE.get((stage or "new").lower(), "new")


def apply_ticket_stage(lead) -> None:
    """Keep ticket_status / resolved_at in step with the sales stage."""
    previous = getattr(lead, "ticket_status", None)
    status = ticket_status_for_stage(getattr(lead, "stage", None))
    # An escalated ticket is work a human owes, even if the sales stage is
    # still "new".
    if status == "new" and getattr(lead, "priority", None) == "important":
        status = "open"
    # Never downgrade an open/in-progress ticket back to "new" just because
    # the sales stage is still new; a human already owes the work.
    if status == "new" and previous in ("open", "in_progress"):
        status = previous
    lead.ticket_status = status
    if status in ("resolved", "closed"):
        if getattr(lead, "resolved_at", None) is None:
            lead.resolved_at = datetime.now(timezone.utc)
    else:
        lead.resolved_at = None


def split_ticket_request(text: str | None) -> tuple[str, bool]:
    """Strip the hidden OPEN_TICKET marker from a model reply."""
    kept: list[str] = []
    opened = False
    for line in (text or "").splitlines():
        if _OPEN_TICKET.match(line):
            opened = True
            continue
        kept.append(line)
    return "\n".join(kept).strip(), opened


def prompt_block(lead) -> str:
    """The LATEST TICKET block injected into the reply prompt."""
    if lead is None:
        return (
            "LATEST TICKET: none. This customer has no ticket yet. Do not say "
            "a ticket is open and do not say the team will follow up. If they "
            "want one, ask a short yes/no question; if they say yes, end your "
            "reply with OPEN_TICKET."
        )
    number = getattr(lead, "ticket_number", None) or "(not numbered)"
    status = getattr(lead, "ticket_status", None) or "new"
    kind = getattr(lead, "ticket_kind", None) or "whatsapp_general"
    summary = (getattr(lead, "summary", None) or getattr(lead, "request", None) or "").strip()
    stage = getattr(lead, "stage", None)
    lines = [
        "LATEST TICKET (this customer):",
        f"- Number: {number}",
        f"- Status: {status}",
        f"- Kind: {kind}",
        f"- Summary: {summary[:300] or '(none)'}",
    ]
    if kind == "whatsapp_sales":
        lines.append(f"- Lead stage: {stage or 'new'} (sales qualification inside this ticket)")
    lines.append(
        "A ticket IS the work object; a lead is only the sales qualification "
        "inside it. Never use the word lead with the customer. Only promise "
        "team follow-up when this block shows a ticket."
    )
    return "\n".join(lines)
