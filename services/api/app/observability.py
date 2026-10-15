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

import json
import logging
import re
import subprocess
import sys
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


# ── Structured JSON logging ──────────────────────────────────────────────
class JsonFormatter(logging.Formatter):
    """One JSON object per log line, so log aggregators can parse it.

    Lives here rather than in main.py so the worker process emits the same
    shape as the API. Two log formats across two processes means a query
    written against one silently misses the other.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id
        if hasattr(record, "tenant_id"):
            log_data["tenant_id"] = record.tenant_id
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    """One readable line for a human watching the terminal.

    Only used when stdout is a TTY. The JSON formatter is what anything
    downstream (Docker, log shippers, aggregators) has to parse, so it stays
    the default whenever output is redirected -- piping this into a file must
    never produce a format the shipper cannot read.

    Extra fields (`request_id`, `tenant_id`) are appended as `key=value` only
    when a record actually carries them, so a plain worker line stays plain.
    """

    LEVEL_STYLE = {
        "DEBUG": ("\033[90m", "\033[0m"),
        "INFO": ("\033[36m", "\033[0m"),
        "WARNING": ("\033[33m", "\033[0m"),
        "ERROR": ("\033[31m", "\033[0m"),
        "CRITICAL": ("\033[1;41m", "\033[0m"),
    }

    def __init__(self, use_color: bool) -> None:
        super().__init__(datefmt="%H:%M:%S")
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        if self.use_color:
            color, reset = self.LEVEL_STYLE.get(record.levelname, ("", ""))
            stamp = f"\033[90m{self.formatTime(record, self.datefmt)}\033[0m"
            level = f"{color}{record.levelname:<8}{reset}"
            name = f"\033[35m{record.name}\033[0m"
        else:
            stamp = self.formatTime(record, self.datefmt)
            level = f"{record.levelname:<8}"
            name = record.name

        line = f"{stamp} {level} {name} | {record.getMessage()}"

        extras = [
            f"{key}={getattr(record, key)}"
            for key in ("request_id", "tenant_id")
            if hasattr(record, key)
        ]
        if extras:
            line += " | " + " ".join(extras)

        # Point at the source line for WARNING+ only. A stack of locations on
        # every INFO line is what makes a console unreadable; when something is
        # actually wrong the location is the thing you want.
        if record.levelno >= logging.WARNING:
            line += f"  ({record.module}:{record.lineno} in {record.funcName}())"

        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)

        return line


def configure_logging(service: str = DEFAULT_SERVICE) -> None:
    """Install the log formatter on the root logger.

    A TTY gets `ConsoleFormatter` (readable); a pipe or file gets
    `JsonFormatter` (machine-parseable). Chosen from the stream, not a setting,
    so `npm run dev`-style piping and `docker logs` both do the right thing
    without anyone remembering a flag.

    `LOG_FORMAT` overrides it outright when you need to force one shape --
    `LOG_FORMAT=json` for a local process you want to paste into a parser, or
    `LOG_FORMAT=console` to read a piped log in your terminal.

    Applied to the root logger (not a single logger) so libraries and worker
    modules are covered without per-module opt-in.
    """
    force = (settings.LOG_FORMAT or "").strip().lower()
    stream = sys.stdout
    if force in ("console", "text", "pretty"):
        formatter = ConsoleFormatter(use_color=stream.isatty())
    elif force == "json":
        formatter = JsonFormatter(datefmt="%Y-%m-%dT%H:%M:%S%z")
    elif stream.isatty():
        formatter = ConsoleFormatter(use_color=True)
    else:
        formatter = JsonFormatter(datefmt="%Y-%m-%dT%H:%M:%S%z")

    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

    # Per-service noise suppression: HTTP access logs are high-volume and
    # low-signal for the worker, which makes no HTTP requests of its own.
    if service == "api":
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
        logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    for noisy in ("sqlalchemy.engine", "httpx", "httpcore", "aiokafka", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)