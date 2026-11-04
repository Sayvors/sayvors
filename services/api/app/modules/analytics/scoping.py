"""Visibility scoping for connected-channel data.

Disconnected channels stay in the database (tokens cleared, data preserved)
so reconnecting restores them. We hide rows whose channel is explicitly
disconnected. A missing channel row is left visible: imported/legacy rows
must not vanish just because their channel was never mirrored locally.
"""
from sqlalchemy import select

from ..channels.models import Channel


def disconnected_channel_ids(user_id: str):
    """Scalar select of the tenant's explicitly disconnected channel ids."""
    return select(Channel.id).where(
        Channel.user_id == user_id,
        Channel.status == "disconnected",
    )
