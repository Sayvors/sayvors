from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_db, get_current_user
from ..users.models import User
from .models import Document as DocumentModel
from .schemas import (
    DatabankCreate,
    DatabankListResponse,
    DatabankResponse,
    DocumentListResponse,
    DocumentResponse,
    IngestJobListResponse,
    IngestJobResponse,
    ScrapeJobResponse,
    ScrapeRequest,
    SearchRequest,
    SearchResponse,
    SearchChunkResponse,
)
from .service import (
    create_databank,
    create_scrape_job,
    delete_databank,
    delete_document,
    get_databank,
    list_databanks,
    list_documents,
    list_ingest_jobs,
    process_document,
    process_pending,
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
    results = await search(databank_id, body, user, db)
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
    )
