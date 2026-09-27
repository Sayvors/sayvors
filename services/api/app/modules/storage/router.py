"""Authenticated endpoints for tenant-owned uploads and object management.

POST   /api/v1/storage/upload          upload photo/video for posts or media
GET    /api/v1/storage/objects         list the caller's uploaded media
GET    /api/v1/storage/objects/{key}   fetch metadata for an owned object
PUT    /api/v1/storage/objects/{key}   replace the content at an owned key
DELETE /api/v1/storage/objects/{key}   delete an owned object
POST   /api/v1/storage/presign        create a temporary private download URL
"""
from __future__ import annotations

import re
from pathlib import Path
from mimetypes import guess_type

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from ...config import settings
from ...core.deps import get_current_user, get_db
from ..rag.models import Databank, Document
from ..users.models import User
from ..media import service as media_service

router = APIRouter(prefix="/api/v1/storage", tags=["storage"])


class ObjectOut(BaseModel):
    key: str
    url: str | None = None
    size: int
    content_type: str
    operation: str = "upload"
    bucket: str | None = None
    etag: str | None = None
    version_id: str | None = None


class PresignBody(BaseModel):
    databank_id: str = Field(..., min_length=1, max_length=80)
    filename: str = Field(..., min_length=1, max_length=255)
    expires_seconds: int = Field(900, ge=1, le=604800)


def _safe_filename(value: str) -> str:
    basename = Path(value or "upload").name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", basename).strip("._")
    return (cleaned or "upload")[:180]


def _storage_upload_error(error: Exception) -> HTTPException:
    """Return actionable AWS failure information without exposing secrets."""
    response = getattr(error, "response", {}) or {}
    aws_error = response.get("Error", {}) if isinstance(response, dict) else {}
    code = str(aws_error.get("Code") or "")
    message = str(aws_error.get("Message") or "")
    if code in {"NoCredentialsError", "PartialCredentialsError", "CredentialRetrievalError"}:
        detail = "AWS credentials are missing in the API process. Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in the same shell that starts Uvicorn, then restart it."
    elif code in {"InvalidAccessKeyId", "SignatureDoesNotMatch", "ExpiredToken", "TokenRefreshRequired"}:
        detail = f"AWS rejected the credentials ({code}). Replace or activate a valid access key, then restart Uvicorn."
    elif code in {"AccessDenied", "AllAccessDisabled", "AuthorizationHeaderMalformed"}:
        detail = f"AWS denied the S3 upload ({code}). Check s3:PutObject on the bucket's media/* path and confirm AWS_REGION is eu-north-1."
    elif code in {"NoSuchBucket", "PermanentRedirect", "301"}:
        detail = f"AWS could not use the configured S3 bucket ({code}). Verify the bucket name and AWS_REGION."
    else:
        detail = f"S3 upload failed ({code or type(error).__name__})"
        if message:
            detail += f": {message[:180]}"
    return HTTPException(status_code=502, detail=detail)


@router.post("/upload", response_model=ObjectOut)
async def upload_object(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    """Upload an image/video and return the durable public URL for post.image_urls."""
    try:
        data = await file.read(max(settings.MEDIA_MAX_MB, 1) * 1024 * 1024 + 1)
        result = await media_service.save_upload(
            user.id,
            _safe_filename(file.filename or "upload"),
            file.content_type,
            data,
            str(request.base_url),
        )
        return ObjectOut(
            key=result["key"], url=result["image_url"], size=result["size"],
            content_type=result["content_type"], operation="upload",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        detail = str(e)
        if "credentials" in detail.lower() or "boto3" in detail.lower():
            detail = "S3 storage is selected, but boto3 or AWS credentials are unavailable to this API process. Install API dependencies and set AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY where Uvicorn is launched, then restart it."
        raise HTTPException(status_code=503, detail=detail[:500]) from e
    except Exception as e:
        raise _storage_upload_error(e) from e
    finally:
        await file.close()


@router.get("/objects")
async def list_objects(user: User = Depends(get_current_user)):
    """List only this tenant's media objects."""
    from ...core.storage import list_media_objects

    return list_media_objects(user.id)


@router.get("/objects/{key:path}")
async def get_object(key: str, user: User = Depends(get_current_user)):
    from ...core.storage import get_media

    safe_key = _owned_key(key, user.id)
    try:
        content = get_media(user.id, safe_key)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="Object not found") from e
    except Exception as e:
        raise HTTPException(status_code=502, detail="Object storage read failed") from e
    media_type = guess_type(Path(safe_key).name)[0] or "application/octet-stream"
    return Response(content=content, media_type=media_type)


@router.put("/objects/{key:path}", response_model=ObjectOut)
async def update_object(
    key: str,
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    from ...core.storage import update_media

    safe_key = _owned_key(key, user.id)
    try:
        from ...core.storage import get_media

        get_media(user.id, safe_key)  # prevent PUT from creating an arbitrary new key
        data = await file.read(max(settings.MEDIA_MAX_MB, 1) * 1024 * 1024 + 1)
        if not data:
            raise ValueError("Empty file.")
        result = update_media(user.id, safe_key, data, file.content_type or "")
        public_url = result.get("url") or f"{str(request.base_url).rstrip('/')}{settings.MEDIA_PUBLIC_PATH}/{user.id}/{Path(safe_key).name}"
        return ObjectOut(
            key=safe_key, url=public_url, size=result["size"],
            content_type=result["content_type"], operation="update",
            bucket=result.get("bucket"), etag=result.get("etag"),
            version_id=result.get("version_id"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="Object not found") from e
    except Exception as e:
        raise HTTPException(status_code=502, detail="Object storage update failed") from e
    finally:
        await file.close()


@router.delete("/objects/{key:path}")
async def delete_object(key: str, user: User = Depends(get_current_user)):
    from ...core.storage import delete_media

    safe_key = _owned_key(key, user.id)
    try:
        return delete_media(user.id, safe_key)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="Object not found") from e
    except Exception as e:
        raise HTTPException(status_code=502, detail="Object storage delete failed") from e


@router.post("/presign")
async def presign_private_document(
    body: PresignBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mint a short-lived GET URL only for a document owned by this tenant."""
    bank = (await db.execute(select(Databank.id).where(
        Databank.id == body.databank_id, Databank.user_id == user.id,
    ))).scalar_one_or_none()
    if not bank:
        raise HTTPException(status_code=404, detail="Databank not found")
    doc = (await db.execute(select(Document.id, Document.file_type).where(
        Document.databank_id == bank,
        Document.user_id == user.id,
        Document.filename == body.filename,
    ))).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    filename = f"{doc.id}.{doc.file_type}"

    from ...core.storage import presign_doc

    try:
        url = presign_doc(bank, filename, body.expires_seconds)
    except RuntimeError as e:
        raise HTTPException(status_code=501, detail=str(e)) from e
    return {"url": url, "expires_in": body.expires_seconds}


def _owned_key(key: str, user_id: str) -> str:
    decoded = key.strip("/")
    if decoded.startswith("media/"):
        decoded = decoded[len("media/"):]
    if not decoded.startswith(f"{user_id}/"):
        raise HTTPException(status_code=404, detail="Object not found")
    parts = decoded.split("/")
    if len(parts) != 2 or any(part in ("", ".", "..") for part in parts):
        raise HTTPException(status_code=404, detail="Object not found")
    return decoded
