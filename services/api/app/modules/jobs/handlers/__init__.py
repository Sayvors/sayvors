"""Job handlers — one module per job type.

Each handler receives a Job row and performs the domain work. Handlers are
pure-ish: they don't manage retry/state — the lane runner does that.
See docs/specs/2026-10-10-unified-job-processing-design.md §A.2 / §C.6
"""

from collections.abc import Callable
from typing import Any

from .stt_job import handle_stt_job
from .tts_job import handle_tts_job

# Closed registry: job_type -> handler coroutine(job, db) -> dict | None
HANDLERS: dict[str, Callable[[Any, Any], Any]] = {
    "stt.job": handle_stt_job,
    "tts.job": handle_tts_job,
}
