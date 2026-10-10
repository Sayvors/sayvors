"""CSV upload + query API routes."""
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_current_user, get_db
from ..users.models import User
from .csv_schemas import CSVUploadResponse, CSVSearchRequest, CSVSearchResult
from .csv_service import (
    upload_csv,
    search_csv_rows,
    list_uploads_for_tenant,
    delete_upload,
    get_rows_paginated,
)
from ..team.context import tenant_id_of, require_perm, TenantContext

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/csv", tags=["csv"])


@router.post("/upload", response_model=CSVUploadResponse)
async def upload(
    file: UploadFile = File(...),
    purpose: str | None = Form(default=None),
    ctx: TenantContext = Depends(require_perm("reviews.view")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a CSV file. Stores metadata + rows as JSONB for AI tool queries."""
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a .csv file")

    content = await file.read()
    if len(content) > 50 * 1024 * 1024:  # 50MB limit
        raise HTTPException(status_code=400, detail="File too large (max 50MB)")

    try:
        return await upload_csv(content, file.filename, tenant_id_of(user), purpose, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/uploads", response_model=list[CSVUploadResponse])
async def list_uploads(
    ctx: TenantContext = Depends(require_perm("reviews.view")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all CSV uploads for this tenant."""
    return await list_uploads_for_tenant(tenant_id_of(user), db)


@router.delete("/uploads/{upload_id}")
async def remove_upload(
    upload_id: str,
    ctx: TenantContext = Depends(require_perm("reviews.view")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a CSV upload and all its rows."""
    ok = await delete_upload(upload_id, tenant_id_of(user), db)
    if not ok:
        raise HTTPException(status_code=404, detail="Upload not found")
    return {"status": "deleted"}


@router.post("/search", response_model=CSVSearchResult)
async def search(
    req: CSVSearchRequest,
    ctx: TenantContext = Depends(require_perm("reviews.view")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Search CSV rows by text across all JSONB values."""
    return await search_csv_rows(
        query=req.query,
        tenant_id=tenant_id_of(user),
        upload_id=req.upload_id,
        purpose=req.purpose,
        filters=req.filters,
        limit=req.limit,
        db=db,
    )


@router.get("/uploads/{upload_id}/rows")
async def get_rows(
    upload_id: str,
    page: int = 1,
    page_size: int = 50,
    ctx: TenantContext = Depends(require_perm("reviews.view")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get paginated rows for a CSV upload."""
    return await get_rows_paginated(upload_id, tenant_id_of(user), page, page_size, db)
