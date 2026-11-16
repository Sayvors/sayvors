import asyncio
import logging

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...core.deps import get_db, get_current_user
from ...database import async_session
from ..users.models import User
from .crawl_service import (
    create_crawl_source,
    delete_crawl_source,
    get_crawl_source,
    list_crawl_sources,
    page_count_for_sources,
    page_status_counts_for_sources,
    update_crawl_source,
)
from .crawler import preview_candidates
from .models import CrawlPage, Document as DocumentModel
from .schemas import (
    AskRequest,
    AskResponse,
    Citation,
    CrawlPageResponse,
    CrawlPreviewResponse,
    CrawlSourceCreate,
    CrawlSourceListResponse,
    CrawlSourceResponse,
    CrawlSourceUpdate,
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

logger = logging.getLogger(__name__)

# Preview/crawl discovery stays bounded: showing the tenant a few hundred
# candidates is enough to select from; the crawl cap itself is max_pages.
PREVIEW_MAX_PAGES = 200


async def require_databank_feature(
    user: User = Depends(get_current_user),
):
    """Gate databank *writes* behind the plan feature. Reads stay open —
    per the billing docs, read-only data is never hidden by a feature gate."""
    from ..billing.entitlements import check_feature
    from ..team.context import tenant_id_of

    await check_feature(tenant_id_of(user), "databank")


@router.post("/databanks", response_model=DatabankResponse, status_code=status.HTTP_201_CREATED)
async def create_new_databank(
    body: DatabankCreate,
    user: User = Depends(get_current_user),
    _gate: None = Depends(require_databank_feature),
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
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    banks = await list_databanks(user, db, limit, offset)
    doc_counts = {}
    for b in banks:
        doc_count = await db.execute(
            select(func.count()).where(DocumentModel.databank_id == b.id)
        )
        doc_counts[b.id] = doc_count.scalar() or 0
    return DatabankListResponse(
        databanks=[
            DatabankResponse(
                id=b.id,
                name=b.name,
                description=b.description,
                accent_color=b.accent_color,
                doc_count=doc_counts.get(b.id, 0),
                created_at=b.created_at,
            )
            for b in banks
        ],
        total=len(banks),
    )


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
    _gate: None = Depends(require_databank_feature),
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
    _gate: None = Depends(require_databank_feature),
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
    _gate: None = Depends(require_databank_feature),
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
    _gate: None = Depends(require_databank_feature),
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


async def _authenticate_preview_user(request: Request) -> User:
    """Dependency: authenticate WITHOUT holding a DB session open.

    Preview can take minutes; keeping the request-scoped session alive that
    long risks stale/closed connections and teardown rollback failures, so
    this opens a short-lived session for auth only. Injectable so tests can
    override it like ``get_current_user``.
    """
    token = request.cookies.get(settings.ACCESS_COOKIE_NAME)
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user_id = payload.get("sub")
    token_type = payload.get("type")
    if not user_id or token_type != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    async with async_session() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

        from ..users.status import suspension_message

        suspended = await suspension_message(db, user)
        if suspended:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=suspended)
        if user.tenant_id and user.tenant_id != user.id:
            from ..team.models import TeamMember

            member = (
                await db.execute(
                    select(TeamMember.status).where(
                        TeamMember.user_id == user.id, TeamMember.tenant_id == user.tenant_id
                    )
                )
            ).scalar_one_or_none()
            if member == "suspended":
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account is suspended")

        from ..auth.rate_limit import is_token_blacklisted

        if await is_token_blacklisted(payload.get("jti", "")):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked")
        if payload.get("ver", 0) != (user.token_version or 0):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked")
        return user


@router.get("/crawl/preview", response_model=CrawlPreviewResponse)
async def preview_crawl_candidates_standalone(
    request: Request,
    url: str = Query(..., min_length=1, max_length=2000),
    scope: str = Query("subtree", pattern="^(single|top|subtree|max_pages)$"),
    max_pages: int = Query(100, ge=1, le=PREVIEW_MAX_PAGES),
    user: User = Depends(_authenticate_preview_user),
):
    """Discover candidate pages before a databank exists (create wizard).

    Read-only page discovery (no content stored) so the user can pick which
    pages to crawl before the databank/source is created.
    """
    try:
        candidates = await asyncio.get_event_loop().run_in_executor(
            None, preview_candidates, url, scope, max_pages
        )
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001 — surface the real cause to the UI
        logger.exception("Crawl preview failed for %s", url)
        raise HTTPException(
            status_code=400,
            detail=f"Could not preview {url}: {type(e).__name__}",
        )
    return CrawlPreviewResponse(
        url=url,
        scope=scope,
        max_pages=max_pages,
        candidates=[
            {"url": c.url, "title": c.title, "status": c.status}
            for c in candidates
        ],
    )


@router.get("/databanks/{databank_id}/crawl/preview", response_model=CrawlPreviewResponse)
async def preview_crawl_candidates(
    databank_id: str,
    url: str = Query(..., min_length=1, max_length=2000),
    scope: str = Query("subtree", pattern="^(single|top|subtree|max_pages)$"),
    max_pages: int = Query(100, ge=1, le=PREVIEW_MAX_PAGES),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Step 1 of the interactive crawl: list pages the crawler would touch.

    No content is fetched or stored here — the tenant uses this list to
    tick the pages they actually want, then creates a source with that
    selection.
    """
    bank = await get_databank(databank_id, user, db)
    if not bank:
        raise HTTPException(status_code=404, detail="Databank not found")
    try:
        candidates = await asyncio.get_event_loop().run_in_executor(
            None, preview_candidates, url, scope, max_pages
        )
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001 — surface the real cause to the UI
        logger.exception("Crawl preview failed for %s", url)
        raise HTTPException(
            status_code=400,
            detail=f"Could not preview {url}: {type(e).__name__}",
        )
    return CrawlPreviewResponse(
        url=url,
        scope=scope,
        max_pages=max_pages,
        candidates=[
            {"url": c.url, "title": c.title, "status": c.status}
            for c in candidates
        ],
    )


@router.post(
    "/databanks/{databank_id}/crawl/sources",
    response_model=CrawlSourceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_crawl_source_endpoint(
    databank_id: str,
    body: CrawlSourceCreate,
    user: User = Depends(get_current_user),
    _gate: None = Depends(require_databank_feature),
    db: AsyncSession = Depends(get_db),
):
    """Step 2: save a source with the user-selected page URLs."""
    bank = await get_databank(databank_id, user, db)
    if not bank:
        raise HTTPException(status_code=404, detail="Databank not found")
    try:
        source = await create_crawl_source(
            db,
            databank_id=databank_id,
            user_id=user.id,
            start_url=body.url,
            scope=body.scope,
            max_pages=body.max_pages,
            sync_enabled=body.sync_enabled,
            sync_interval_minutes=body.sync_interval_minutes,
            urls=body.urls,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    counts = await page_count_for_sources(db, [source.id])
    status_counts = await page_status_counts_for_sources(db, [source.id])
    return CrawlSourceResponse(
        id=source.id,
        databank_id=source.databank_id,
        start_url=source.start_url,
        scope=source.scope,
        max_pages=source.max_pages,
        sync_enabled=source.sync_enabled,
        sync_interval_minutes=source.sync_interval_minutes,
        next_sync_at=source.next_sync_at,
        last_sync_at=source.last_sync_at,
        last_status=source.last_status,
        error=source.error,
        created_at=source.created_at,
        page_count=counts.get(source.id, 0),
        page_status_counts=status_counts.get(source.id, {}),
    )


@router.get("/databanks/{databank_id}/crawl/sources", response_model=CrawlSourceListResponse)
async def list_crawl_sources_endpoint(
    databank_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    bank = await get_databank(databank_id, user, db)
    if not bank:
        raise HTTPException(status_code=404, detail="Databank not found")
    sources, total = await list_crawl_sources(
        db, databank_id=databank_id, user_id=user.id, limit=limit, offset=offset
    )
    counts = await page_count_for_sources(db, [s.id for s in sources])
    status_counts = await page_status_counts_for_sources(db, [s.id for s in sources])
    return CrawlSourceListResponse(
        sources=[
            CrawlSourceResponse(
                id=s.id,
                databank_id=s.databank_id,
                start_url=s.start_url,
                scope=s.scope,
                max_pages=s.max_pages,
                sync_enabled=s.sync_enabled,
                sync_interval_minutes=s.sync_interval_minutes,
                next_sync_at=s.next_sync_at,
                last_sync_at=s.last_sync_at,
                last_status=s.last_status,
                error=s.error,
                created_at=s.created_at,
                page_count=counts.get(s.id, 0),
                page_status_counts=status_counts.get(s.id, {}),
            )
            for s in sources
        ],
        total=total,
    )


@router.get(
    "/databanks/{databank_id}/crawl/sources/{source_id}/pages",
    response_model=list[CrawlPageResponse],
)
async def list_crawl_source_pages(
    databank_id: str,
    source_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The selected pages of a source (statuses after crawls)."""
    bank = await get_databank(databank_id, user, db)
    if not bank:
        raise HTTPException(status_code=404, detail="Databank not found")
    try:
        source = await get_crawl_source(db, databank_id, user.id, source_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Crawl source not found")
    pages = (
        await db.execute(
            select(CrawlPage)
            .where(CrawlPage.source_id == source.id)
            .order_by(CrawlPage.url)
        )
    ).scalars().all()
    return [
        CrawlPageResponse(
            id=p.id,
            url=p.url,
            title=p.title,
            status=p.status,
            content_hash=p.content_hash,
            word_count=p.word_count,
            lang=p.lang,
            fetched_at=p.fetched_at,
            document_id=p.document_id,
            error=p.error,
            updated_at=p.updated_at,
        )
        for p in pages
    ]


@router.patch(
    "/databanks/{databank_id}/crawl/sources/{source_id}",
    response_model=CrawlSourceResponse,
)
async def update_crawl_source_endpoint(
    databank_id: str,
    source_id: str,
    body: CrawlSourceUpdate,
    user: User = Depends(get_current_user),
    _gate: None = Depends(require_databank_feature),
    db: AsyncSession = Depends(get_db),
):
    bank = await get_databank(databank_id, user, db)
    if not bank:
        raise HTTPException(status_code=404, detail="Databank not found")
    values = body.model_dump(exclude_unset=True)
    try:
        source = await update_crawl_source(
            db,
            databank_id=databank_id,
            user_id=user.id,
            source_id=source_id,
            values=values,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="Crawl source not found")
    counts = await page_count_for_sources(db, [source.id])
    status_counts = await page_status_counts_for_sources(db, [source.id])
    return CrawlSourceResponse(
        id=source.id,
        databank_id=source.databank_id,
        start_url=source.start_url,
        scope=source.scope,
        max_pages=source.max_pages,
        sync_enabled=source.sync_enabled,
        sync_interval_minutes=source.sync_interval_minutes,
        next_sync_at=source.next_sync_at,
        last_sync_at=source.last_sync_at,
        last_status=source.last_status,
        error=source.error,
        created_at=source.created_at,
        page_count=counts.get(source.id, 0),
        page_status_counts=status_counts.get(source.id, {}),
    )


@router.delete(
    "/databanks/{databank_id}/crawl/sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_crawl_source_endpoint(
    databank_id: str,
    source_id: str,
    user: User = Depends(get_current_user),
    _gate: None = Depends(require_databank_feature),
    db: AsyncSession = Depends(get_db),
):
    bank = await get_databank(databank_id, user, db)
    if not bank:
        raise HTTPException(status_code=404, detail="Databank not found")
    try:
        await delete_crawl_source(
            db, databank_id=databank_id, user_id=user.id, source_id=source_id
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="Crawl source not found")


@router.post(
    "/databanks/{databank_id}/process",
    response_model=IngestJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def process_all_pending(
    databank_id: str,
    user: User = Depends(get_current_user),
    _gate: None = Depends(require_databank_feature),
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
    _gate: None = Depends(require_databank_feature),
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
    _gate: None = Depends(require_databank_feature),
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
    _gate: None = Depends(require_databank_feature),
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
    _gate: None = Depends(require_databank_feature),
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
    _gate: None = Depends(require_databank_feature),
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
    """Agentic answer: the tenant's model reasons over the tools
    (vector, keyword, live DB)."""
    from ..llm.gateway import ProviderError
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
    _gate: None = Depends(require_databank_feature),
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
