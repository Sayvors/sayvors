"""Activity feed (§31 Phase B): organized log composed from ingest jobs,
crawl runs and failed pages — newest first, bounded length.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.modules.rag.activity import databank_activity
from app.modules.rag.models import CrawlPage, CrawlSource, Databank, Document, IngestJob

_BANK = "activity-bank-0001"
_USER = "activity-user-0001"


async def _seed(db) -> None:
    db.add(Databank(id=_BANK, user_id=_USER, name="Activity Bank"))
    await db.flush()

    doc = Document(
        id=str(uuid.uuid4()), databank_id=_BANK, user_id=_USER,
        filename="page.md", source_type="scrape", file_type="md", status="pending",
    )
    db.add(doc)
    await db.flush()
    db.add(IngestJob(
        id=str(uuid.uuid4()), user_id=_USER, databank_id=_BANK,
        document_id=doc.id, job_type="scrape", status="completed",
        progress=100, stage="Done",
        created_at=datetime.now(timezone.utc) - timedelta(minutes=2),
        updated_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    ))

    source = CrawlSource(
        id=str(uuid.uuid4()), databank_id=_BANK, user_id=_USER,
        start_url="https://example.com/", scope="subtree", max_pages=10,
        last_status="success",
        last_sync_at=datetime.now(timezone.utc),
    )
    db.add(source)
    await db.flush()
    db.add(CrawlPage(
        id=str(uuid.uuid4()), source_id=source.id,
        url="https://example.com/broken", status="failed", error="HTTP 500",
        updated_at=datetime.now(timezone.utc),
    ))
    await db.commit()


@pytest.mark.asyncio
async def test_activity_feed_orders_and_labels(db):
    await _seed(db)

    events = await databank_activity(db, databank_id=_BANK, user_id=_USER)

    assert events, "feed must not be empty"
    types = {e["type"] for e in events}
    assert {"ingest", "crawl", "error"} <= types

    crawl_event = next(e for e in events if e["type"] == "crawl")
    assert crawl_event["title"] == "https://example.com/"
    assert crawl_event["status"] == "success"

    error_event = next(e for e in events if e["type"] == "error")
    assert error_event["title"] == "https://example.com/broken"
    assert "HTTP 500" in error_event["detail"]

    ingest_event = next(e for e in events if e["type"] == "ingest")
    assert ingest_event["status"] == "done"
    assert ingest_event["title"] == "page.md"

    # Newest first: crawl run (now) > failed page (now) > ingest (2 min ago).
    assert events[0]["type"] in ("crawl", "error")


@pytest.mark.asyncio
async def test_activity_feed_is_tenant_scoped(db):
    await _seed(db)

    other = await databank_activity(
        db, databank_id=_BANK, user_id="someone-else-0002"
    )
    assert other == []

    rows = (
        await db.execute(select(IngestJob).where(IngestJob.databank_id == _BANK))
    ).scalars().all()
    assert rows  # sanity: data exists, scoping did the filtering
