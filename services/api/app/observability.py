"""Centralised GlitchTip (Sentry-compatible) error monitoring.

Single source of truth for every observability decision. Each process that
should report errors calls `init_observability()` once at startup:

    app/main.py          -> init_observability("api")
    app/workers/main.py  -> init_observability("worker")

This is per-process by necessity, not by accident: `sentry_sdk.init()` patches
logging / SQLAlchemy / Redis handlers *inside the calling process only*. There
is no cross-process propagation, so a new entrypoint that forgets to initialise
fails silently -- exactly how the worker loops were invisible until now.

Keep all Sentry/GlitchTip configuration here. Do not re-introduce ad-hoc
`sentry_sdk.init()` calls in individual modules: duplicate init silently
discards the first configuration, and config drift across entrypoints is how
worker errors get lost.
"""

import logging
import re
import subprocess
from pathlib import Path
from typing import Any

import sentry_sdk
from sentry_sdk import Hub, Scope

from .config import settings

logger = logging.getLogger(__name__)

# Service name -> environment suffix reported to GlitchTip. Keeping the service
# in the environment lets you filter `api` vs `worker` issues in the UI without
# polluting release tracking.
DEFAULT_SERVICE = "api"

# Keys scrubbed from event payloads before they leave the process. send_default_pii
# is False, but request bodies and exception args can still carry secrets we
# logged ourselves, so scrub defensively rather than trusting every call site.
_SENSITIVE_KEY_RE = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|authorization|cookie|"
    r"client[_-]?secret|private[_-]?key|session|refresh[_-]?token)",
    re.IGNORECASE,
)
_SCRUBBED = "[redacted]"


def _git_sha() -> str | None:
    """Best-effort short commit SHA, used to tag releases.

    Falls back to None when git is unavailable (e.g. slim containers), so a
    missing git binary degrades release tagging rather than breaking startup.
    """
    try:
        root = Path(__file__).resolve().parents[2]
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        sha = out.stdout.strip()
        return sha or None
    except Exception:
        return None


def build_release() -> str:
    """Release identifier: project@version@sha when a SHA is available.

    GlitchTip groups issues by release, which is what makes 'did this deploy fix
    it?' answerable. Pinning to the commit SHA means a release maps to exactly
    one build rather than drifting every time VERSION is bumped.
    """
    version = settings.VERSION or "unknown"
    sha = _git_sha()
    return f"sayvors-api@{version}@{sha}" if sha else f"sayvors-api@{version}"


def build_environment(service: str) -> str:
    """Environment identifier, namespaced by service."""
    base = settings.ENVIRONMENT or "development"
    return f"{base}-{service}" if service else base


def _scrub(value: Any, _depth: int = 0) -> Any:
    """Recursively redact sensitive-looking values in event payloads."""
    if _depth > 6:
        return value
    if isinstance(value, dict):
        return {
            k: (_SCRUBBED if _SENSITIVE_KEY_RE.search(str(k)) else _scrub(v, _depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_scrub(v, _depth + 1) for v in value]
    return value


def _before_send(event: dict, hint: dict) -> dict | None:
    """Drop noisy events and redact secrets before transmission."""
    if hint.get("exc_info") is not None:
        exc_type, exc_value, _tb = hint["exc_info"]
        # Health-probe noise: /health and /readyz are polled by orchestrators and
        # fail during restarts; surfacing them buries real issues.
        if getattr(exc_type, "__name__", "") in {"ConnectionRefusedError"} and exc_value:
            return None
    return _scrub(event)


# Idempotency guard. Repeated init in one process (lifespan restart, reload,
# double entrypoint) would otherwise discard the first config and log warnings.
_configured = False


def init_observability(service: str = DEFAULT_SERVICE) -> bool:
    """Initialise GlitchTip reporting for the current process.

    Returns True if an SDK client is active afterwards. Never raises: losing
    observability must not prevent the service from starting.
    """
    global _configured

    dsn = settings.GLITCHTIP_DSN
    if not dsn:
        logger.info("GLITCHTIP_DSN unset; error reporting disabled")
        return False
    if _configured:
        return True

    try:
        sentry_sdk.init(
            dsn=dsn,
            environment=build_environment(service),
            release=build_release(),
            traces_sample_rate=0.1,
            profiles_sample_rate=0.1,
            # No user emails/IPs by default. Opt in explicitly if ever needed.
            send_default_pii=False,
            before_send=_before_send,
        )
        _configured = True
        logger.info(
            "GlitchTip initialised: service=%s environment=%s release=%s",
            service,
            build_environment(service),
            build_release(),
        )
        return True
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("GlitchTip init failed: %s", e)
        return False