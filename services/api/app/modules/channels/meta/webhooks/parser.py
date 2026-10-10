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
            # contacts rides beside messages on the value, never inside a
            # message — profile_name here is what the inbox names threads by.
            value_contacts = value.get("contacts") or []
            profile_name = (
                (value_contacts[0].get("profile") or {}).get("name")
                if value_contacts
                else None
            )
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
                            # The sender's WhatsApp profile name, so the inbox
                            # shows "Ahmed Khan" instead of a bare number.
                            "profile_name": profile_name,
                            # Reactions carry their emoji here, not in text.
                            "reaction": msg.get("reaction"),
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
                event_type = "account.update"
                field_val = change.get("field", "")
                # Coexistence: partner_removed disconnect
                if field_val == "partner_removed":
                    event_type = "connection.disconnect"
                events.append(
                    {
                        "external_asset_id": phone_number_id,
                        "external_event_id": f"account-{entry.get('id', '')}-{field_val}",
                        "event_type": event_type,
                        "occurred_at": _now_iso(),
                        "data": {"field": field_val, "value": value},
                    }
                )
            # Coexistence: history sync messages (past messages)
            if change.get("field") == "history":
                for msg in value.get("messages", []):
                    events.append({
                        "external_asset_id": phone_number_id,
                        "external_event_id": msg.get("id", ""),
                        "event_type": "message.history",
                        "occurred_at": _ts(msg.get("timestamp")),
                        "data": {
                            "from": msg.get("from"),
                            "msg_type": msg.get("type"),
                            "text": ((msg.get("text") or {}).get("body")),
                            "context": msg.get("context"),
                            "profile_name": profile_name,
                            "reaction": msg.get("reaction"),
                        },
                    })
            # Coexistence: SMB contacts sync
            if change.get("field") == "smb_app_state_sync":
                contacts = value.get("contacts", [])
                events.append({
                    "external_asset_id": phone_number_id,
                    "external_event_id": f"smb-contacts-{entry.get('id', '')}",
                    "event_type": "smb.contacts",
                    "occurred_at": _now_iso(),
                    "data": {"contacts": contacts},
                })
            # Coexistence: Business app message echoes (sent via app after onboarding)
            if change.get("field") == "smb_message_echoes":
                for msg in value.get("messages", []):
                    events.append({
                        "external_asset_id": phone_number_id,
                        "external_event_id": msg.get("id", ""),
                        "event_type": "message.echo",
                        "occurred_at": _ts(msg.get("timestamp")),
                        "data": {
                            "from": msg.get("from"),
                            "to": msg.get("to"),
                            "msg_type": msg.get("type"),
                            "text": ((msg.get("text") or {}).get("body")),
                            "context": msg.get("context"),
                            "reaction": msg.get("reaction"),
                        },
                    })
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
                        # The mid lives inside value.message, not on value —
                        # a stable id is what makes replay dedupe work.
                        "external_event_id": (
                            (value.get("message") or {}).get("mid")
                            or value.get("mid")
                            or f"msg-{entry.get('time', '')}"
                        ),
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
                            # When it was written on Instagram (our stored
                            # created_at is only when we processed it) and
                            # which comment this replies to, so the inbox
                            # can thread conversations.
                            "timestamp": value.get("timestamp"),
                            "parent_id": value.get("parent_id"),
                        },
                    }
                )
            elif field in ("messages", "messaging_handovers", "standby"):
                events.append(
                    {
                        "external_asset_id": ig_id,
                        # The mid lives inside value.message, not on value —
                        # a stable id is what makes replay dedupe work.
                        "external_event_id": (
                            (value.get("message") or {}).get("mid")
                            or value.get("mid")
                            or f"{field}-{entry.get('time', '')}"
                        ),
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
        # Page-linked IG accounts deliver DMs on a top-level `messaging`
        # array (no changes/field wrapper) — this is what Meta actually
        # sends: {"entry": [{"id": ig-id, "messaging": [{"sender": ...,
        # "recipient": ..., "message": {"mid", "text"}}]}]}.
        for msg in entry.get("messaging", []):
            message = msg.get("message")
            if not message:
                continue  # read receipts / deliveries — history only
            events.append(
                {
                    "external_asset_id": ig_id,
                    "external_event_id": message.get("mid")
                    or f"messaging-{entry.get('time', '')}",
                    "event_type": "message.received",
                    "occurred_at": _now_iso(),
                    "data": {
                        "field": "messages",
                        "raw": {
                            "sender": msg.get("sender"),
                            "recipient": msg.get("recipient"),
                            "timestamp": msg.get("timestamp"),
                            "message": message,
                        },
                    },
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
