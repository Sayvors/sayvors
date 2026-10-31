"""WhatsApp interactive messages: reply buttons, list menus, CTA links.

Meta's limits are strict and rejecting a message costs the customer their
reply, so every payload is validated here, once, for both callers: the AI
reply path (a `CHOICES:` line in the model output) and the inbox API.

Docs: https://developers.facebook.com/docs/whatsapp/cloud-api/guides/send-message-templates#interactive-messages
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

MAX_BUTTONS = 3
MAX_BUTTON_TITLE = 20
MAX_LIST_ROWS = 10
MAX_LIST_ROW_TITLE = 24
MAX_LIST_ROW_DESCRIPTION = 72
MAX_SECTION_TITLE = 24
MAX_BODY = 1024
MAX_HEADER = 60
MAX_FOOTER = 60
MAX_LIST_BUTTON = 20
MAX_CTA_DISPLAY = 20
MAX_BUTTON_ID = 256

# The model is asked to finish with exactly this line when it offers 2-3 next
# steps. Anchored to a whole line so prose that happens to contain "CHOICES:"
# is left alone.
_CHOICES_RE = re.compile(r"(?im)^\s*CHOICES\s*:\s*(\[[^\n]*\])\s*$")


def split_choices(text: str | None) -> tuple[str, list[str]]:
    """(reply without the directive line, button titles).

    The directive line is ALWAYS stripped when present, even if the labels are
    invalid: leaving `CHOICES: [...]` in the customer's message is worse than
    losing the buttons. Invalid labels therefore degrade to plain text.
    """
    if not text:
        return text or "", []
    match = None
    for match in _CHOICES_RE.finditer(text):
        pass
    if match is None:
        return text, []
    stripped = (text[: match.start()] + text[match.end():]).rstrip()
    try:
        raw = json.loads(match.group(1))
    except ValueError:
        return stripped, []
    if not isinstance(raw, list):
        return stripped, []
    titles = [str(item).strip()[:MAX_BUTTON_TITLE] for item in raw]
    titles = [t for t in titles if t]
    if not (2 <= len(titles) <= MAX_BUTTONS):
        return stripped, []
    if len({t.lower() for t in titles}) != len(titles):
        return stripped, []
    return stripped, titles


def _header(header: str | None) -> dict | None:
    if not header:
        return None
    return {"type": "text", "text": header.strip()[:MAX_HEADER]}


def _footer(footer: str | None) -> dict | None:
    if not footer:
        return None
    return {"text": footer.strip()[:MAX_FOOTER]}


def _body(body: str) -> dict:
    text = (body or "").strip()
    if not text:
        raise ValueError("an interactive message needs body text")
    return {"text": text[:MAX_BODY]}


def build_buttons(
    body: str,
    titles: list[str],
    *,
    header: str | None = None,
    footer: str | None = None,
) -> dict:
    """interactive object of type=button. Titles become reply ids."""
    cleaned: list[str] = []
    for title in titles:
        value = str(title or "").strip()
        if not value:
            continue
        if len(value) > MAX_BUTTON_TITLE:
            raise ValueError(
                f"button title {value!r} is longer than {MAX_BUTTON_TITLE} characters"
            )
        cleaned.append(value)
    if not (1 <= len(cleaned) <= MAX_BUTTONS):
        raise ValueError(f"interactive buttons need 1-{MAX_BUTTONS} titles")
    if len({t.lower() for t in cleaned}) != len(cleaned):
        raise ValueError("button titles must be unique")
    # Stable ids: the tap comes back as the title text, so the id only has to
    # be unique inside this message.
    buttons = [
        {"type": "reply", "reply": {"id": f"choice_{index + 1}", "title": title}}
        for index, title in enumerate(cleaned)
    ]
    interactive = {
        "type": "button",
        "body": _body(body),
        "action": {"buttons": buttons},
    }
    if (head := _header(header)):
        interactive["header"] = head
    if (foot := _footer(footer)):
        interactive["footer"] = foot
    return interactive


def build_list(
    body: str,
    button_text: str,
    sections: list[dict],
    *,
    header: str | None = None,
    footer: str | None = None,
) -> dict:
    """interactive object of type=list. sections=[{title, rows:[{id,title,description}]}]."""
    label = str(button_text or "").strip()
    if not label:
        raise ValueError("a list message needs a button label")
    if len(label) > MAX_LIST_BUTTON:
        raise ValueError(f"list button label must be <= {MAX_LIST_BUTTON} characters")

    cleaned_sections: list[dict] = []
    total_rows = 0
    for section in sections or []:
        if not isinstance(section, dict):
            continue
        rows: list[dict] = []
        for row in section.get("rows") or []:
            if not isinstance(row, dict):
                continue
            row_id = str(row.get("id") or "").strip()
            title = str(row.get("title") or "").strip()
            if not row_id or not title:
                continue
            payload = {"id": row_id[:MAX_BUTTON_ID], "title": title[:MAX_LIST_ROW_TITLE]}
            description = str(row.get("description") or "").strip()
            if description:
                payload["description"] = description[:MAX_LIST_ROW_DESCRIPTION]
            rows.append(payload)
        if not rows:
            continue
        total_rows += len(rows)
        cleaned_sections.append({
            "title": str(section.get("title") or "").strip()[:MAX_SECTION_TITLE],
            "rows": rows,
        })

    if not cleaned_sections or total_rows == 0:
        raise ValueError("a list message needs at least one row")
    if total_rows > MAX_LIST_ROWS:
        raise ValueError(f"a list message allows at most {MAX_LIST_ROWS} rows")

    interactive = {
        "type": "list",
        "body": _body(body),
        "action": {"button": label, "sections": cleaned_sections},
    }
    if (head := _header(header)):
        interactive["header"] = head
    if (foot := _footer(footer)):
        interactive["footer"] = foot
    return interactive


def build_cta_url(
    body: str,
    display_text: str,
    url: str,
    *,
    header: str | None = None,
    footer: str | None = None,
) -> dict:
    """interactive object of type=cta_url."""
    label = str(display_text or "").strip()
    if not label:
        raise ValueError("a CTA message needs display text")
    if len(label) > MAX_CTA_DISPLAY:
        raise ValueError(f"CTA display text must be <= {MAX_CTA_DISPLAY} characters")
    target = str(url or "").strip()
    if not target.startswith(("https://", "http://")):
        raise ValueError("CTA url must be an absolute http(s) URL")
    interactive = {
        "type": "cta_url",
        "body": _body(body),
        "action": {
            "name": "cta_url",
            "parameters": {"display_text": label, "url": target},
        },
    }
    if (head := _header(header)):
        interactive["header"] = head
    if (foot := _footer(footer)):
        interactive["footer"] = foot
    return interactive


def readable_content(body: str, titles: list[str] | None = None) -> str:
    """What the inbox stores for an interactive message.

    `ChannelMessage` has no payload column, and adding one for rendering would
    be a migration for a cosmetic gain. The body plus the offered options is
    what a human needs to read in the thread.
    """
    text = (body or "").strip()
    if titles:
        text = f"{text}\n\nOptions: {' · '.join(titles)}".strip()
    return text
