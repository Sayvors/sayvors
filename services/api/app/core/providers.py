"""Publish-provider seam for media.

Locations writes are native Google only (Business Information API) and do
not use a provider flag. Media publishing still has a seam because Google's
media upload is not implemented yet; the flag defaults to "localith" and a
premature "google" flip fails loudly with NotImplementedError.

Set via environment: MEDIA_PUBLISH_PROVIDER.
"""
import os

LOCALITH = "localith"
GOOGLE = "google"

_VALID = (LOCALITH, GOOGLE)


def _read(env_name: str) -> str:
    value = (os.environ.get(env_name, LOCALITH) or LOCALITH).strip().lower()
    if value not in _VALID:
        raise ValueError(f"{env_name} must be 'localith' or 'google', got {value!r}")
    return value


def media_publish_provider() -> str:
    """Who publishes photos to Google."""
    return _read("MEDIA_PUBLISH_PROVIDER")


def google_not_ready(which: str) -> NotImplementedError:
    """Loud failure for flipping a seam before its native client exists."""
    return NotImplementedError(
        f"Google native {which} is not implemented yet — it lands with "
        f"GBP API access. The provider flag is set to 'google' without "
        f"an implementation behind it."
    )
