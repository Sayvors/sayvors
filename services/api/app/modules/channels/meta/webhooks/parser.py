"""Provider webhook parsers: raw Meta payload -> flat raw events.

Each raw event: {provider, external_asset_id, external_event_id, event_type,
occurred_at, data}. Tenant resolution happens in the router via meta_assets.
"""
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse(payload: dict) -> tuple[str, list[dict]]:
    """Dispatch on payload `object`. Returns (provider, raw_events)."""
    obj = payload.get("object", "")
    if obj == "whatsapp_business_account":
        return "whatsapp", _parse_whatsapp(payload)
    if obj == "page":
        return "facebook", _parse_page(payload)
    if obj == "instagram":
        return "instagram", _parse_instagram(payload)
    return "unknown", []


def _parse_whatsapp(payload: dict) -> list[dict]:
    events: list[dict] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            metadata = value.get("metadata", {})
            phone_number_id = metadata.get("phone_number_id", "")
            for msg in value.get("messages", []):
                events.append(
                    {
                        "external_asset_id": phone_number_id,
                        "external_event_id": msg.get("id", ""),
                        "event_type": "message.received",
                        "occurred_at": _ts(msg.get("timestamp")),
                        "data": {
                            "from": msg.get("from"),
                            "msg_type": msg.get("type"),
                            "text": ((msg.get("text") or {}).get("body")),
                            "context": msg.get("context"),
                        },
                    }
                )
            for st in value.get("statuses", []):
                events.append(
                    {
                        "external_asset_id": phone_number_id,
                        "external_event_id": st.get("id", ""),
                        "event_type": "message.status",
                        "occurred_at": _ts(st.get("timestamp")),
                        "data": {
                            "to": st.get("recipient_id"),
                            "status": st.get("status"),
                            "errors": st.get("errors"),
                        },
                    }
                )
            # Account-level changes (new ids, quality updates, ...).
            if value.get("phone_number_id") and not value.get("messages") and not value.get("statuses"):
                events.append(
                    {
                        "external_asset_id": phone_number_id,
                        "external_event_id": f"account-{entry.get('id', '')}-{change.get('field', 'update')}",
                        "event_type": "account.update",
                        "occurred_at": _now_iso(),
                        "data": {"field": change.get("field"), "value": value},
                    }
                )
    return [e for e in events if e["external_event_id"]]


def _parse_page(payload: dict) -> list[dict]:
    events: list[dict] = []
    for entry in payload.get("entry", []):
        page_id = str(entry.get("id", ""))
        for change in entry.get("changes", []):
            value = change.get("value", {})
            field = change.get("field", "")
            if field in ("feed", "mention"):
                item = value.get("item", "")
                verb = value.get("verb", "")
                if item == "comment" and verb in ("add", "edited"):
                    events.append(
                        {
                            "external_asset_id": page_id,
                            "external_event_id": value.get("comment_id", ""),
                            "event_type": "comment.received",
                            "occurred_at": _ts(value.get("created_time")),
                            "data": {
                                "post_id": value.get("post_id"),
                                "message": value.get("message"),
                                "from": value.get("from"),
                            },
                        }
                    )
                elif item in ("post", "status") and verb == "add":
                    events.append(
                        {
                            "external_asset_id": page_id,
                            "external_event_id": value.get("post_id", ""),
                            "event_type": "post.published",
                            "occurred_at": _ts(value.get("created_time")),
                            "data": {"message": value.get("message")},
                        }
                    )
            elif field == "messages":
                # Messenger payloads are nested; keep raw for Phase 2.
                events.append(
                    {
                        "external_asset_id": page_id,
                        "external_event_id": value.get("mid", f"msg-{entry.get('time', '')}"),
                        "event_type": "message.received",
                        "occurred_at": _now_iso(),
                        "data": {"raw": value},
                    }
                )
    return [e for e in events if e["external_event_id"]]


def _parse_instagram(payload: dict) -> list[dict]:
    events: list[dict] = []
    for entry in payload.get("entry", []):
        ig_id = str(entry.get("id", ""))
        for change in entry.get("changes", []):
            field = change.get("field", "")
            value = change.get("value", {})
            if field == "comments":
                events.append(
                    {
                        "external_asset_id": ig_id,
                        "external_event_id": value.get("id", ""),
                        "event_type": "comment.received",
                        "event_type_detail": field,
                        "occurred_at": _now_iso(),
                        "data": {
                            "text": value.get("text"),
                            "media_id": value.get("media", {}).get("id")
                            if isinstance(value.get("media"), dict)
                            else value.get("media_id"),
                            "from": value.get("from"),
                        },
                    }
                )
            elif field in ("messages", "messaging_handovers", "standby"):
                events.append(
                    {
                        "external_asset_id": ig_id,
                        "external_event_id": value.get("mid", f"{field}-{entry.get('time', '')}"),
                        "event_type": "message.received",
                        "occurred_at": _now_iso(),
                        "data": {"field": field, "raw": value},
                    }
                )
            elif field == "mentions":
                events.append(
                    {
                        "external_asset_id": ig_id,
                        "external_event_id": value.get("comment_id") or value.get("media_id", ""),
                        "event_type": "mention.received",
                        "occurred_at": _now_iso(),
                        "data": {"raw": value},
                    }
                )
    return [e for e in events if e["external_event_id"]]


def _ts(value) -> str:
    """Meta timestamps: unix seconds or ISO-ish. Best-effort normalize."""
    if not value:
        return _now_iso()
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).isoformat()
    except ValueError:
        return _now_iso()
