"""Publish/write provider seams (Localith today, Google native when GBP API lands).

Each tenant's reviews/replies/metrics already route per channel (OAuth
tokens → native Google, otherwise Localith), so those need no seam. The
three direct Localith call sites are different — they assume Localith:

- locations write-back  (locations/service.py)
- media publishing      (media/service.py)
- posts publishing      (posts/service.py — stays on Localith permanently;
  Google's Posts API is hotel-only, so Localith remains the posts partner
  by decision, not by accident)

The two flags below default to "localith": zero behavior change. Setting
either to "google" before the native client exists fails loudly with
NotImplementedError (never silently) — when GBP API access lands, the swap
is: implement the google branch at the marked seam + flip the flag.

Set via environment: LOCATIONS_WRITE_PROVIDER, MEDIA_PUBLISH_PROVIDER.
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


def locations_write_provider() -> str:
    """Who receives location profile writes (description/hours/etc.)."""
    return _read("LOCATIONS_WRITE_PROVIDER")


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
