"""rag.ingest job handler — wraps the RAG ingest pipeline.

Payload contract:
    {
        "ingest_job_id": str,   # the IngestJob row id
    }

The handler looks up the IngestJob, runs the existing pipeline
(_process_document_job or _process_databank_job), and updates both the
IngestJob (projection) and the unified Job row.
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...rag.jobs import _process_document_job, _process_databank_job
from ...rag.models import IngestJob
from ..models import Job
from ..service import complete_job, fail_job

logger = logging.getLogger(__name__)


async def handle_rag_ingest(job: Job, db: AsyncSession) -> dict | None:
    payload = job.payload or {}
    ingest_job_id = payload.get("ingest_job_id")
    if not ingest_job_id:
        raise ValueError("ingest_job_id missing from payload")

    ingest_job = (
        await db.execute(select(IngestJob).where(IngestJob.id == ingest_job_id))
    ).scalar_one_or_none()
    if ingest_job is None:
        raise ValueError(f"IngestJob {ingest_job_id} not found")

    # Idempotency: already completed.
    if ingest_job.status == "completed":
        return {"status": "already_completed", "ingest_job_id": ingest_job.id}

    try:
        if ingest_job.document_id:
            await _process_document_job(ingest_job, db)
        else:
            await _process_databank_job(ingest_job, db)

        ingest_job.status = "completed"
        ingest_job.progress = 100
        ingest_job.stage = "Done"
        db.add(ingest_job)
        await db.commit()

        await complete_job(db, job=job, result={"status": "completed", "ingest_job_id": ingest_job.id})
        await db.commit()

        return {"status": "completed", "ingest_job_id": ingest_job.id}

    except Exception as e:
        logger.exception("RAG ingest job %s failed", ingest_job_id)
        ingest_job.status = "failed"
        ingest_job.error = str(e)[:2000]
        ingest_job.stage = "Failed"
        db.add(ingest_job)
        await db.commit()

        await fail_job(db, job=job, error_code="ingest_failed", error=str(e))
        await db.commit()
        raise
