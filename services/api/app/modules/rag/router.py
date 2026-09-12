from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_db, get_current_user
from ..users.models import User
from .models import Document as DocumentModel
from .schemas import (
    AskRequest,
    AskResponse,
    Citation,
    DatabankCreate,
    DatabankListResponse,
    DatabankResponse,
    DatabaseConnection,
    DatabaseSourceCreate,
    DatabaseSourceListResponse,
    DatabaseSourceResponse,
    DatabaseTestResponse,
    DocumentListResponse,
    DocumentResponse,
    IngestJobListResponse,
    IngestJobResponse,
    IngestQueryRequest,
    QueryRequest,
    QueryResponse,
    SchemaResponse,
    ScrapeJobResponse,
    ScrapeRequest,
    SearchRequest,
    SearchResponse,
    SearchChunkResponse,
    TableInfo,
    TablePreviewResponse,
    TraceStep,
)
from .service import (
    create_databank,
    create_scrape_job,
    create_source,
    delete_databank,
    delete_document,
    delete_source,
    get_databank,
    get_source,
    ingest_query_results,
    list_databanks,
    list_documents,
    list_ingest_jobs,
    list_sources,
    preview_document,
    process_document,
    process_pending,
    reindex_databank,
    search,
    upload_document,
)

router = APIRouter(prefix="/api/v1/rag", tags=["rag"])


@router.post("/databanks", response_model=DatabankResponse, status_code=status.HTTP_201_CREATED)
async def create_new_databank(
    body: DatabankCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    bank = await create_databank(body, user, db)
    return DatabankResponse(
        id=bank.id,
        name=bank.name,
        description=bank.description,
        accent_color=bank.accent_color,
        created_at=bank.created_at,
    )


@router.get("/databanks", response_model=DatabankListResponse)
async def list_all_databanks(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    banks = await list_databanks(user, db)
    responses = []
    for b in banks:
        doc_count = await db.execute(
            select(func.count()).where(DocumentModel.databank_id == b.id)
        )
        responses.append(
            DatabankResponse(
                id=b.id,
                name=b.name,
                description=b.description,
                accent_color=b.accent_color,
                doc_count=doc_count.scalar() or 0,
                created_at=b.created_at,
            )
        )
    return DatabankListResponse(databanks=responses, total=len(responses))


@router.get("/databanks/{databank_id}", response_model=DatabankResponse)
async def get_single_databank(
    databank_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    bank = await get_databank(databank_id, user, db)
    if not bank:
        raise HTTPException(status_code=404, detail="Databank not found")
    return DatabankResponse(
        id=bank.id,
        name=bank.name,
        description=bank.description,
        accent_color=bank.accent_color,
        created_at=bank.created_at,
    )


@router.delete("/databanks/{databank_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_single_databank(
    databank_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    deleted = await delete_databank(databank_id, user, db)
    if not deleted:
        raise HTTPException(status_code=404, detail="Databank not found")


@router.post(
    "/databanks/{databank_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_new_document(
    databank_id: str,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    bank = await get_databank(databank_id, user, db)
    if not bank:
        raise HTTPException(status_code=404, detail="Databank not found")
    doc = await upload_document(databank_id, file, user, db)
    # Auto-process: parse, chunk, embed immediately
    try:
        await process_document(doc.id, user, db)
    except Exception:
        pass  # Job queued; status will update async
    return DocumentResponse(
        id=doc.id,
        filename=doc.filename,
        source_type=doc.source_type,
        source_url=doc.source_url,
        file_type=doc.file_type,
        size_bytes=doc.size_bytes,
        status=doc.status,
        chunk_count=doc.chunk_count,
        created_at=doc.created_at,
    )


@router.get("/databanks/{databank_id}/documents", response_model=DocumentListResponse)
async def list_all_documents(
    databank_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    docs, total = await list_documents(databank_id, user, db, limit, offset)
    return DocumentListResponse(
        documents=[
            DocumentResponse(
                id=d.id,
                filename=d.filename,
                source_type=d.source_type,
                source_url=d.source_url,
                file_type=d.file_type,
                size_bytes=d.size_bytes,
                status=d.status,
                chunk_count=d.chunk_count,
                created_at=d.created_at,
            )
            for d in docs
        ],
        total=total,
    )


@router.delete(
    "/databanks/{databank_id}/documents/{doc_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_single_document(
    databank_id: str,
    doc_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    deleted = await delete_document(doc_id, user, db)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")


@router.get("/databanks/{databank_id}/documents/{doc_id}/preview")
async def preview_single_document(
    databank_id: str,
    doc_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Show the actual uploaded content: table for CSV, text chunks otherwise."""
    try:
        return await preview_document(databank_id, doc_id, user, db, page, page_size)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post(
    "/databanks/{databank_id}/scrape",
    response_model=ScrapeJobResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_new_scrape_job(
    databank_id: str,
    body: ScrapeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    bank = await get_databank(databank_id, user, db)
    if not bank:
        raise HTTPException(status_code=404, detail="Databank not found")
    job = await create_scrape_job(databank_id, body, user, db)
    return ScrapeJobResponse(
        id=job.id,
        url=job.url,
        crawl_mode=job.crawl_mode,
        status=job.status,
        pages_found=job.pages_found,
        error=job.error,
        created_at=job.created_at,
    )


@router.post(
    "/databanks/{databank_id}/process",
    response_model=IngestJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def process_all_pending(
    databank_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    bank = await get_databank(databank_id, user, db)
    if not bank:
        raise HTTPException(status_code=404, detail="Databank not found")
    try:
        job = await process_pending(databank_id, user, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return IngestJobResponse(
        id=job.id,
        job_type=job.job_type,
        status=job.status,
        progress=job.progress,
        stage=job.stage,
        error=job.error,
        created_at=job.created_at,
    )


@router.post(
    "/databanks/{databank_id}/documents/{doc_id}/process",
    response_model=IngestJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def process_single_document(
    databank_id: str,
    doc_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        job = await process_document(doc_id, user, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return IngestJobResponse(
        id=job.id,
        job_type=job.job_type,
        status=job.status,
        progress=job.progress,
        stage=job.stage,
        error=job.error,
        created_at=job.created_at,
    )


@router.get("/jobs", response_model=IngestJobListResponse)
async def get_ingest_jobs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    jobs, total = await list_ingest_jobs(user, db, limit, offset)
    return IngestJobListResponse(
        jobs=[
            IngestJobResponse(
                id=j.id,
                job_type=j.job_type,
                status=j.status,
                progress=j.progress,
                stage=j.stage,
                error=j.error,
                created_at=j.created_at,
            )
            for j in jobs
        ],
        total=total,
    )


@router.post(
    "/databanks/{databank_id}/search",
    response_model=SearchResponse,
)
async def search_databank(
    databank_id: str,
    body: SearchRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    bank = await get_databank(databank_id, user, db)
    if not bank:
        raise HTTPException(status_code=404, detail="Databank not found")
    results, degraded = await search(databank_id, body, user, db)
    return SearchResponse(
        chunks=[
            SearchChunkResponse(
                content=r["content"],
                score=r["score"],
                document_id=r["document_id"],
                metadata_=r.get("metadata_"),
            )
            for r in results
        ],
        query=body.query,
        degraded=degraded,
        notice=(
            "Vector search unavailable (no embedding backend) — keyword results only."
            if degraded
            else None
        ),
    )


def _source_response(source) -> DatabaseSourceResponse:
    return DatabaseSourceResponse(
        id=source.id,
        name=source.name,
        db_type=source.db_type,
        host=source.host,
        port=source.port,
        database=source.database,
        username=source.username,
        created_at=source.created_at,
    )


async def _owned_source(databank_id: str, source_id: str, user, db):
    from .service import get_databank as _get_bank

    bank = await _get_bank(databank_id, user, db)
    if not bank:
        raise HTTPException(status_code=404, detail="Databank not found")
    source = await get_source(source_id, user, db)
    if not source or source.databank_id != databank_id:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@router.post(
    "/databanks/{databank_id}/sources/test",
    response_model=DatabaseTestResponse,
)
async def test_database_source(
    databank_id: str,
    body: DatabaseConnection,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Test a database connection without saving it."""
    from .service import get_databank as _get_bank, _source_config
    from .connectors import test_connection

    bank = await _get_bank(databank_id, user, db)
    if not bank:
        raise HTTPException(status_code=404, detail="Databank not found")
    try:
        result = await test_connection(_source_config(body))
        return DatabaseTestResponse(ok=True, version=result["version"])
    except ValueError as e:
        return DatabaseTestResponse(ok=False, error=str(e)[:500])


@router.post(
    "/databanks/{databank_id}/sources",
    response_model=DatabaseSourceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def save_database_source(
    databank_id: str,
    body: DatabaseSourceCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Test + save a named database connection (password stored encrypted)."""
    try:
        source = await create_source(body, user, databank_id, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _source_response(source)


@router.get(
    "/databanks/{databank_id}/sources",
    response_model=DatabaseSourceListResponse,
)
async def list_database_sources(
    databank_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        sources = await list_sources(databank_id, user, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return DatabaseSourceListResponse(
        sources=[_source_response(s) for s in sources], total=len(sources)
    )


@router.delete(
    "/databanks/{databank_id}/sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_database_source(
    databank_id: str,
    source_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _owned_source(databank_id, source_id, user, db)
    await delete_source(source_id, user, db)


@router.get(
    "/databanks/{databank_id}/sources/{source_id}/schema",
    response_model=SchemaResponse,
)
async def read_source_schema(
    databank_id: str,
    source_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from .service import _config_from_source
    from .connectors import list_tables

    source = await _owned_source(databank_id, source_id, user, db)
    try:
        tables = await list_tables(_config_from_source(source))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)[:500])
    return SchemaResponse(
        source_id=source.id, tables=[TableInfo(**t) for t in tables]
    )


@router.get(
    "/databanks/{databank_id}/sources/{source_id}/tables/{table}",
    response_model=TablePreviewResponse,
)
async def preview_source_table(
    databank_id: str,
    source_id: str,
    table: str,
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from .service import _config_from_source
    from .connectors import preview_table

    source = await _owned_source(databank_id, source_id, user, db)
    try:
        preview = await preview_table(_config_from_source(source), table, limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)[:500])
    return TablePreviewResponse(**preview)


@router.post(
    "/databanks/{databank_id}/sources/{source_id}/query",
    response_model=QueryResponse,
)
async def run_source_query(
    databank_id: str,
    source_id: str,
    body: QueryRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run a read-only SELECT/WITH query live and return rows."""
    from .service import _config_from_source
    from .connectors import run_query

    source = await _owned_source(databank_id, source_id, user, db)
    try:
        result = await run_query(_config_from_source(source), body.sql, body.limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)[:500])
    return QueryResponse(**result)


@router.post(
    "/databanks/{databank_id}/reindex",
    status_code=status.HTTP_202_ACCEPTED,
)
async def reindex_single_databank(
    databank_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Re-embed every document (e.g. after switching embedding providers)."""
    try:
        queued = await reindex_databank(databank_id, user, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"queued": queued}


@router.post(
    "/databanks/{databank_id}/retry",
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_stuck_documents(
    databank_id: str,
    body: dict | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retry stuck/failed docs without deleting anything.

    Body (optional): {"document_ids": ["..."]} to retry specific docs.
    Without body, retries all docs in pending/processing/failed status.
    """
    from .service import retry_documents

    doc_ids = (body or {}).get("document_ids")
    try:
        queued = await retry_documents(databank_id, user, db, doc_ids)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"queued": queued}


@router.post(
    "/databanks/{databank_id}/ask",
    response_model=AskResponse,
)
async def ask_databank(
    databank_id: str,
    body: AskRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Agentic answer: Gemini reasons over tools (vector, keyword, live DB)."""
    from ..llm.providers.base import ProviderError
    from .agent import ask_question

    try:
        result = await ask_question(
            databank_id, body.question, user, db,
            top_k=body.top_k, max_steps=body.max_steps,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ProviderError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return AskResponse(
        answer=result["answer"],
        citations=[Citation(**c) for c in result["citations"]],
        trace=[TraceStep(**t) for t in result["trace"]],
        steps_used=result["steps_used"],
        model=result["model"],
    )


@router.post(
    "/databanks/{databank_id}/sources/{source_id}/ingest",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_source_query(
    databank_id: str,
    source_id: str,
    body: IngestQueryRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run a query, store the result set as a document, and queue embedding."""
    source = await _owned_source(databank_id, source_id, user, db)
    try:
        doc = await ingest_query_results(
            source, body.sql, body.name, body.limit, user, db
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)[:500])
    try:
        await process_document(doc.id, user, db)
    except ValueError:
        pass
    return DocumentResponse(
        id=doc.id,
        filename=doc.filename,
        source_type=doc.source_type,
        source_url=doc.source_url,
        file_type=doc.file_type,
        size_bytes=doc.size_bytes,
        status=doc.status,
        chunk_count=doc.chunk_count,
        created_at=doc.created_at,
    )
