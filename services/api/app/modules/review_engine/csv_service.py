"""CSV upload, parse, store, and query service."""
import csv
import io
import json
import logging
import uuid

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from .csv_models import CSVRow, CSVUpload
from .csv_schemas import CSVSearchResult, CSVUploadResponse

logger = logging.getLogger(__name__)


async def upload_csv(
    file_content: bytes,
    filename: str,
    tenant_id: str,
    purpose: str | None,
    db: AsyncSession,
) -> CSVUploadResponse:
    """Parse CSV bytes, store metadata + rows in DB."""
    upload_id = str(uuid.uuid4())

    text_content = file_content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text_content))
    rows = list(reader)

    if not rows:
        raise ValueError("CSV file is empty or has no data rows")

    column_names = list(rows[0].keys())

    upload = CSVUpload(
        id=upload_id,
        tenant_id=tenant_id,
        filename=filename,
        column_names=column_names,
        row_count=len(rows),
        purpose=purpose,
    )
    db.add(upload)

    for idx, row in enumerate(rows):
        cleaned = {k.strip(): (v.strip() if v else None) for k, v in row.items() if k}
        db.add(CSVRow(
            id=str(uuid.uuid4()),
            upload_id=upload_id,
            row_index=idx,
            data=cleaned,
        ))

    await db.commit()
    logger.info("Uploaded CSV %s: %d rows, %d columns for tenant %s", filename, len(rows), len(column_names), tenant_id)

    return CSVUploadResponse(
        id=upload_id,
        filename=filename,
        column_names=column_names,
        row_count=len(rows),
        purpose=purpose,
    )


async def search_csv_rows(
    query: str,
    tenant_id: str,
    upload_id: str | None,
    purpose: str | None,
    filters: dict | None,
    limit: int,
    db: AsyncSession,
) -> CSVSearchResult:
    """Search CSV rows by text match across all JSONB values."""
    base_query = (
        select(CSVRow)
        .join(CSVUpload, CSVRow.upload_id == CSVUpload.id)
        .where(CSVUpload.tenant_id == tenant_id)
    )

    if upload_id:
        base_query = base_query.where(CSVRow.upload_id == upload_id)
    if purpose:
        base_query = base_query.where(CSVUpload.purpose == purpose)

    # Text search: cast each JSONB value to text and search with LIKE
    # Use PostgreSQL's jsonb_each_text for searching
    search_pattern = f"%{query.lower()}%"
    base_query = base_query.where(
        text("EXISTS (SELECT 1 FROM jsonb_each_text(csv_rows.data) WHERE lower(value) LIKE :pat)")
    ).params(pat=search_pattern)

    # Apply JSONB filters
    if filters:
        for key, value in filters.items():
            base_query = base_query.where(
                text("csv_rows.data @> :filter_json")
            ).params(filter_json=json.dumps({key: value}))

    base_query = base_query.order_by(CSVRow.row_index).limit(limit)
    result = await db.execute(base_query)
    rows = result.scalars().all()

    return CSVSearchResult(
        rows=[CSVRowOut(id=r.id, row_index=r.row_index, data=r.data or {}) for r in rows],
        total_matches=len(rows),
    )


async def get_upload_for_tenant(upload_id: str, tenant_id: str, db: AsyncSession) -> CSVUpload | None:
    result = await db.execute(
        select(CSVUpload).where(CSVUpload.id == upload_id, CSVUpload.tenant_id == tenant_id)
    )
    return result.scalar_one_or_none()


async def list_uploads_for_tenant(tenant_id: str, db: AsyncSession) -> list[CSVUploadResponse]:
    result = await db.execute(
        select(CSVUpload).where(CSVUpload.tenant_id == tenant_id).order_by(CSVUpload.created_at.desc())
    )
    uploads = result.scalars().all()
    return [
        CSVUploadResponse(
            id=u.id, filename=u.filename, column_names=u.column_names,
            row_count=u.row_count, purpose=u.purpose,
        )
        for u in uploads
    ]


async def delete_upload(upload_id: str, tenant_id: str, db: AsyncSession) -> bool:
    upload = await get_upload_for_tenant(upload_id, tenant_id, db)
    if not upload:
        return False
    await db.delete(upload)
    await db.commit()
    return True


async def get_rows_paginated(
    upload_id: str,
    tenant_id: str,
    page: int,
    page_size: int,
    db: AsyncSession,
) -> dict:
    """Get paginated rows for a specific upload."""
    upload = await get_upload_for_tenant(upload_id, tenant_id, db)
    if not upload:
        return {"rows": [], "total": 0, "page": page, "page_size": page_size}

    # Count total
    count_result = await db.execute(
        select(func.count(CSVRow.id)).where(CSVRow.upload_id == upload_id)
    )
    total = count_result.scalar() or 0

    # Fetch page
    offset = (page - 1) * page_size
    result = await db.execute(
        select(CSVRow)
        .where(CSVRow.upload_id == upload_id)
        .order_by(CSVRow.row_index)
        .offset(offset)
        .limit(page_size)
    )
    rows = result.scalars().all()

    return {
        "rows": [CSVRowOut(id=r.id, row_index=r.row_index, data=r.data or {}) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
