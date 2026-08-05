import hashlib
import os
import uuid
from datetime import datetime, timezone

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ..users.models import User
from .cache import content_hash, set_progress
from .chunker import chunk_text
from .embeddings import get_embedding_provider
from .models import Databank, Document, DocumentChunk, IngestJob, ScrapeJob
from .search import hybrid_search
from .schemas import (
    DatabankCreate,
    SearchRequest,
    ScrapeRequest,
)


async def create_databank(
    body: DatabankCreate, user: User, db: AsyncSession
) -> Databank:
    bank = Databank(
        id=str(uuid.uuid4()),
        user_id=user.id,
        name=body.name,
        description=body.description,
        accent_color=body.accent_color,
    )
    db.add(bank)
    await db.commit()
    await db.refresh(bank)
    return bank


async def list_databanks(user: User, db: AsyncSession) -> list[Databank]:
    result = await db.execute(
        select(Databank)
        .where(Databank.user_id == user.id)
        .order_by(Databank.created_at.desc())
    )
    return list(result.scalars().all())


async def get_databank(
    databank_id: str, user: User, db: AsyncSession
) -> Databank | None:
    result = await db.execute(
        select(Databank).where(
            Databank.id == databank_id, Databank.user_id == user.id
        )
    )
    return result.scalar_one_or_none()


async def delete_databank(
    databank_id: str, user: User, db: AsyncSession
) -> bool:
    bank = await get_databank(databank_id, user, db)
    if not bank:
        return False

    await db.execute(
        DocumentChunk.__table__.delete().where(
            DocumentChunk.databank_id == databank_id
        )
    )
    await db.execute(
        Document.__table__.delete().where(Document.databank_id == databank_id)
    )
    await db.execute(
        IngestJob.__table__.delete().where(IngestJob.databank_id == databank_id)
    )
    await db.execute(
        ScrapeJob.__table__.delete().where(ScrapeJob.databank_id == databank_id)
    )
    await db.delete(bank)
    await db.commit()
    return True


async def upload_document(
    databank_id: str, file: UploadFile, user: User, db: AsyncSession
) -> Document:
    ext = (file.filename or "unknown").rsplit(".", 1)[-1].lower()
    if ext not in ("pdf", "docx", "txt", "md", "csv", "xlsx", "sql"):
        raise ValueError(f"Unsupported file type: {ext}")

    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ValueError(f"File too large. Maximum size is {settings.MAX_UPLOAD_SIZE_MB}MB.")

    c_hash = hashlib.sha256(content).hexdigest()

    doc = Document(
        id=str(uuid.uuid4()),
        databank_id=databank_id,
        user_id=user.id,
        filename=file.filename or "unnamed",
        source_type="upload",
        file_type=ext,
        size_bytes=len(content),
        status="pending",
        content_hash=c_hash,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    upload_dir = os.path.join(settings.UPLOAD_DIR, databank_id)
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, f"{doc.id}.{ext}")
    with open(file_path, "wb") as f:
        f.write(content)

    return doc


async def list_documents(
    databank_id: str, user: User, db: AsyncSession, limit: int = 50, offset: int = 0
) -> tuple[list[Document], int]:
    count_result = await db.execute(
        select(func.count()).where(
            Document.databank_id == databank_id, Document.user_id == user.id
        )
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        select(Document)
        .where(Document.databank_id == databank_id, Document.user_id == user.id)
        .order_by(Document.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all()), total


async def delete_document(doc_id: str, user: User, db: AsyncSession) -> bool:
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.user_id == user.id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        return False

    await db.execute(
        DocumentChunk.__table__.delete().where(DocumentChunk.document_id == doc_id)
    )
    await db.delete(doc)
    await db.commit()
    return True


async def create_scrape_job(
    databank_id: str, body: ScrapeRequest, user: User, db: AsyncSession
) -> ScrapeJob:
    job = ScrapeJob(
        id=str(uuid.uuid4()),
        databank_id=databank_id,
        user_id=user.id,
        url=body.url,
        crawl_mode=body.crawl_mode,
        max_pages=body.max_pages,
        status="pending",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def process_pending(
    databank_id: str, user: User, db: AsyncSession
) -> IngestJob:
    result = await db.execute(
        select(Document).where(
            Document.databank_id == databank_id,
            Document.user_id == user.id,
            Document.status == "pending",
        )
    )
    pending_docs = list(result.scalars().all())
    if not pending_docs:
        raise ValueError("No pending documents to process")

    job = IngestJob(
        id=str(uuid.uuid4()),
        user_id=user.id,
        databank_id=databank_id,
        job_type="upload",
        status="queued",
        progress=0,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    from .jobs import enqueue_job, start_worker

    await enqueue_job(str(job.id))
    await start_worker()

    return job


async def process_document(doc_id: str, user: User, db: AsyncSession) -> IngestJob:
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.user_id == user.id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise ValueError("Document not found")

    job = IngestJob(
        id=str(uuid.uuid4()),
        user_id=user.id,
        databank_id=doc.databank_id,
        document_id=doc.id,
        job_type="upload",
        status="queued",
        progress=0,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    from .jobs import enqueue_job, start_worker

    await enqueue_job(str(job.id))
    await start_worker()

    return job


async def list_ingest_jobs(
    user: User, db: AsyncSession, limit: int = 20, offset: int = 0
) -> tuple[list[IngestJob], int]:
    count_result = await db.execute(
        select(func.count()).where(IngestJob.user_id == user.id)
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        select(IngestJob)
        .where(IngestJob.user_id == user.id)
        .order_by(IngestJob.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all()), total


async def search(
    databank_id: str, body: SearchRequest, user: User, db: AsyncSession
) -> list[dict]:
    provider = await get_embedding_provider()
    vectors = await provider.embed([body.query])
    query_vector = vectors[0]

    results = await hybrid_search(
        databank_id=databank_id,
        query_vector=query_vector,
        query_text=body.query,
        top_k=body.top_k,
        db=db,
    )
    return results


async def _parse_document(doc: Document) -> str:
    from .parsers.pdf import parse_pdf
    from .parsers.docx import parse_docx
    from .parsers.xlsx import parse_xlsx
    from .parsers.csv import parse_csv
    from .parsers.sql import parse_sql
    from .parsers.text import parse_text

    file_path = os.path.join(settings.UPLOAD_DIR, doc.databank_id, f"{doc.id}.{doc.file_type}")
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Document file not found: {file_path}")

    with open(file_path, "rb") as f:
        content = f.read()

    parsers = {
        "pdf": parse_pdf,
        "docx": parse_docx,
        "xlsx": parse_xlsx,
        "csv": parse_csv,
        "sql": parse_sql,
        "txt": parse_text,
        "md": parse_text,
    }
    parser = parsers.get(doc.file_type)
    if not parser:
        raise ValueError(f"No parser for file type: {doc.file_type}")

    return await parser(content)


async def _embed_and_store(
    doc: Document, chunks: list[dict], job: IngestJob
) -> None:
    from ...database import async_session

    async with async_session() as db:
        provider = await get_embedding_provider()
        texts = [c["content"] for c in chunks]

        batch_size = 64
        all_vectors: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            vectors = await provider.embed(batch)
            all_vectors.extend(vectors)

        db_chunks = []
        for idx, (chunk, vector) in enumerate(zip(chunks, all_vectors)):
            db_chunk = DocumentChunk(
                id=str(uuid.uuid4()),
                document_id=doc.id,
                databank_id=doc.databank_id,
                content=chunk["content"],
                embedding=vector,
                embedding_model=provider.__class__.__name__,
                seq=idx,
                token_count=chunk["token_count"],
            )
            db_chunks.append(db_chunk)

        db.add_all(db_chunks)

        doc.status = "completed"
        doc.chunk_count = len(db_chunks)

        job.progress = 100
        job.stage = "Done"

        await db.commit()
