"""Job handlers — one module per job type.

Each handler receives a Job row and performs the domain work. Handlers are
pure-ish: they don't manage retry/state — the lane runner does that.
See docs/specs/2026-10-10-unified-job-processing-design.md §A.2 / §C.6
"""

from collections.abc import Callable
from typing import Any

from .stt_job import handle_stt_job
from .tts_job import handle_tts_job
from .post_publish import handle_post_publish
from .post_delete import handle_post_delete
from .rag_ingest import handle_rag_ingest
from .review_request_send import handle_review_request_send

# Closed registry: job_type -> handler coroutine(job, db) -> dict | None
HANDLERS: dict[str, Callable[[Any, Any], Any]] = {
    "stt.job": handle_stt_job,
    "tts.job": handle_tts_job,
    "post.publish": handle_post_publish,
    "post.delete": handle_post_delete,
    "rag.ingest": handle_rag_ingest,
    "review_request.send": handle_review_request_send,
}
