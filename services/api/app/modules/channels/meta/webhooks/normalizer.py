"""Normalized internal Meta events (provider-agnostic envelope)."""
import uuid


def normalize(
    raw_event: dict,
    provider: str,
    tenant_id: str | None,
    connection_id: str | None,
) -> dict:
    """Build the envelope the rest of Sayvors consumes (Phase 2)."""
    return {
        "event_id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "connection_id": connection_id,
        "provider": provider,
        "event_type": raw_event.get("event_type", "unknown"),
        "external_asset_id": raw_event.get("external_asset_id"),
        "external_event_id": raw_event.get("external_event_id"),
        "occurred_at": raw_event.get("occurred_at"),
        "payload": raw_event.get("data", {}),
    }
