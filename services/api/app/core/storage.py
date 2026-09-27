"""Shared file storage: Google Cloud Storage with local-disk fallback.

Two classes of files, two buckets:
- MEDIA (public): owner photos/videos that go to Google. The provider
  fetches them by URL, so objects are public and put_media returns a
  public https URL.
- DOCS (private): databank uploads, scrapes, exports. Never public;
  workers read them back with get_doc_bytes.

Backend selection per class: S3 bucket, then GCS bucket, otherwise local disk
(UPLOAD_DIR layout, byte-identical to the historic paths).

GCS setup (one time, documented in deploy/env.prod.example):
- two buckets, e.g. sayvors-media (uniform PUBLIC access) and
  sayvors-private (private);
- a service account with object rights on both, exposed the standard way
  via GOOGLE_APPLICATION_CREDENTIALS (file path mounted as a secret).

The google-cloud-storage import is LAZY: without the package installed
(e.g. unit tests) only the local backend works, and GCS selection raises
a clear error only if actually attempted.
"""
import logging
import os
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)


def _settings():
    from ..config import settings

    return settings


# ── backend selection ─────────────────────────────────────────────

def media_configured() -> bool:
    return _media_backend() != "local"


def docs_configured() -> bool:
    return _docs_backend() != "local"


def _media_backend() -> str:
    from integrations.storage import s3

    if s3.configured("media"):
        return "s3"
    return "gcs" if (_settings().GCS_PUBLIC_BUCKET or "").strip() else "local"


def _docs_backend() -> str:
    from integrations.storage import s3

    if s3.configured("docs"):
        return "s3"
    return "gcs" if (_settings().GCS_PRIVATE_BUCKET or "").strip() else "local"


def _gcs_client():
    try:
        from google.cloud import storage as _gcs
    except ImportError as e:
        raise RuntimeError(
            "google-cloud-storage is not installed; cannot use GCS backend."
        ) from e
    return _gcs.Client()


def _public_url(bucket: str, key: str) -> str:
    return f"https://storage.googleapis.com/{bucket}/{key}"


# ── local layout (historic paths, unchanged) ──────────────────────

def _local_media_root() -> Path:
    path = Path(_settings().MEDIA_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _local_doc_path(databank_id: str, filename: str) -> Path:
    return Path(_settings().UPLOAD_DIR) / databank_id / filename


# ── media (public) ────────────────────────────────────────────────

def put_media(user_id: str, filename: str, data: bytes, content_type: str | None) -> tuple[str, str]:
    """Store a media file. Returns (storage_key, public_url).

    Public-bucket objects are only ever served as image/* or video/*; a
    caller-supplied type outside that set (or a missing one) degrades to
    application/octet-stream so an attacker can never store renderable
    HTML/SVG on a public URL.
    """
    ext = Path(filename or "").suffix.lower()
    stored = f"{uuid.uuid4().hex}{ext}"
    safe_type = (
        content_type
        if content_type and (content_type.startswith("image/") or content_type.startswith("video/"))
        else "application/octet-stream"
    )
    if _media_backend() == "s3":
        from integrations.storage import s3

        key = f"{user_id}/{stored}"
        result = s3.put("media", key, data, safe_type)
        return key, result["url"]
    if _media_backend() == "gcs":
        settings = _settings()
        key = f"media/{user_id}/{stored}"
        client = _gcs_client()
        blob = client.bucket(settings.GCS_PUBLIC_BUCKET.strip()).blob(key)
        blob.upload_from_string(data, content_type=safe_type)
        try:
            blob.make_public()
        except Exception as e:
            # Uniform-public buckets need no per-object ACL; anything else
            # surfaces here instead of failing silently into a 403 later.
            logger.debug("GCS make_public skipped/failed for %s: %s", key, e)
        return key, _public_url(settings.GCS_PUBLIC_BUCKET.strip(), key)
    dest = _local_media_root() / user_id / stored
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return stored, ""  # public URL needs the request origin; caller builds it


def delete_media(user_id: str, storage_key: str) -> dict:
    if _media_backend() == "s3":
        from integrations.storage import s3

        key = storage_key
        if key.startswith(f"media/{user_id}/"):
            key = key[len("media/"):]
        elif not key.startswith(f"{user_id}/"):
            key = f"{user_id}/{Path(key).name}"
        return s3.delete("media", key)
    if _media_backend() == "gcs":
        key = storage_key
        if key.startswith(f"media/{user_id}/"):
            key = key[len("media/"):]
        elif not key.startswith(f"{user_id}/"):
            key = f"{user_id}/{Path(key).name}"
        full_key = f"media/{key}"
        _gcs_client().bucket(_settings().GCS_PUBLIC_BUCKET.strip()).blob(full_key).delete()
        return {"deleted": True, "bucket": _settings().GCS_PUBLIC_BUCKET.strip(), "key": full_key}
    target = _local_media_root() / user_id / Path(storage_key).name
    existed = target.exists()
    target.unlink(missing_ok=True)
    return {"deleted": existed, "key": f"{user_id}/{target.name}"}


# ── docs (private) ────────────────────────────────────────────────

def _doc_key(databank_id: str, filename: str) -> str:
    return f"docs/{databank_id}/{filename}"


def put_doc(databank_id: str, filename: str, data: bytes) -> dict | None:
    if _docs_backend() == "s3":
        from integrations.storage import s3

        return s3.put("docs", f"{databank_id}/{filename}", data, "application/octet-stream")
    if _docs_backend() == "gcs":
        settings = _settings()
        _gcs_client().bucket(settings.GCS_PRIVATE_BUCKET.strip()).blob(
            _doc_key(databank_id, filename)
        ).upload_from_string(data, content_type="application/octet-stream")
        return {"operation": "upload", "bucket": settings.GCS_PRIVATE_BUCKET.strip(),
            "key": _doc_key(databank_id, filename), "size": len(data)}
    path = _local_doc_path(databank_id, filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"operation": "upload", "key": f"{databank_id}/{filename}", "size": len(data)}


def get_doc(databank_id: str, filename: str) -> bytes:
    if _docs_backend() == "s3":
        from integrations.storage import s3

        try:
            return s3.get("docs", f"{databank_id}/{filename}")
        except FileNotFoundError as e:
            raise FileNotFoundError(f"Document file not found: {filename}") from e
    if _docs_backend() == "gcs":
        from google.api_core.exceptions import NotFound as _NotFound

        try:
            return _gcs_client().bucket(
                _settings().GCS_PRIVATE_BUCKET.strip()
            ).blob(_doc_key(databank_id, filename)).download_as_bytes()
        except _NotFound as e:
            raise FileNotFoundError(f"Document file not found: {filename}") from e
    path = _local_doc_path(databank_id, filename)
    if not path.exists():
        raise FileNotFoundError(f"Document file not found: {path}")
    return path.read_bytes()


def get_doc_with_metadata(databank_id: str, filename: str) -> dict:
    """Read a private document and return its content plus backend metadata."""
    if _docs_backend() == "s3":
        from integrations.storage import s3

        return s3.get_with_metadata("docs", f"{databank_id}/{filename}")
    content = get_doc(databank_id, filename)
    if _docs_backend() == "gcs":
        bucket = _settings().GCS_PRIVATE_BUCKET.strip()
        blob = _gcs_client().bucket(bucket).blob(_doc_key(databank_id, filename))
        blob.reload()
        return {"content": content, "bucket": bucket, "key": _doc_key(databank_id, filename),
                "size": blob.size, "content_type": blob.content_type, "etag": blob.etag,
                "last_modified": blob.updated.isoformat() if blob.updated else None}
    return {"content": content, "bucket": None, "key": f"{databank_id}/{filename}",
            "size": len(content), "content_type": "application/octet-stream"}


def presign_doc(databank_id: str, filename: str, expires_seconds: int = 900) -> str:
    """Create a temporary URL for downloading a private object."""
    if _docs_backend() == "s3":
        from integrations.storage import s3

        return s3.presign_get("docs", f"{databank_id}/{filename}", expires_seconds)
    if _docs_backend() == "gcs":
        blob = _gcs_client().bucket(_settings().GCS_PRIVATE_BUCKET.strip()).blob(
            _doc_key(databank_id, filename)
        )
        return blob.generate_signed_url(expiration=max(1, min(expires_seconds, 604800)))
    raise RuntimeError("Signed URLs are unavailable for local storage.")


def delete_doc(databank_id: str, filename: str) -> dict:
    if _docs_backend() == "s3":
        from integrations.storage import s3

        return s3.delete("docs", f"{databank_id}/{filename}")
    if _docs_backend() == "gcs":
        _gcs_client().bucket(_settings().GCS_PRIVATE_BUCKET.strip()).blob(
            _doc_key(databank_id, filename)
        ).delete()
        return {"deleted": True, "bucket": _settings().GCS_PRIVATE_BUCKET.strip(),
                "key": _doc_key(databank_id, filename)}
    target = _local_doc_path(databank_id, filename)
    existed = target.exists()
    target.unlink(missing_ok=True)
    return {"deleted": existed, "key": f"{databank_id}/{filename}"}


def delete_bank(databank_id: str) -> dict:
    """Remove every file of one databank (best effort)."""
    if _docs_backend() == "s3":
        from integrations.storage import s3

        try:
            return s3.delete_prefix("docs", databank_id)
        except Exception as e:
            logger.debug("S3 databank delete failed for %s: %s", databank_id, e)
            return {"deleted": False, "reason": "provider_error"}
    if _docs_backend() == "gcs":
        try:
            bucket = _gcs_client().bucket(_settings().GCS_PRIVATE_BUCKET.strip())
            for blob in bucket.list_blobs(prefix=_doc_key(databank_id, "")):
                try:
                    blob.delete()
                except Exception:
                    pass
        except Exception as e:
            logger.debug("GCS bank delete failed for %s: %s", databank_id, e)
            return {"deleted": False, "reason": "provider_error"}
        return {"deleted": True, "bucket": _settings().GCS_PRIVATE_BUCKET.strip(),
                "prefix": _doc_key(databank_id, "")}
    import shutil

    target = Path(_settings().UPLOAD_DIR) / databank_id
    existed = target.exists()
    shutil.rmtree(target, ignore_errors=True)
    return {"deleted": existed, "prefix": databank_id}


def local_media_url(base_url: str, user_id: str, storage_key: str) -> str:
    settings = _settings()
    return (
        f"{base_url.rstrip('/')}{settings.MEDIA_PUBLIC_PATH}/{user_id}/{storage_key}"
    )


def storage_status() -> dict:
    """For health/debug endpoints: which backend each class uses (no secrets)."""
    settings = _settings()
    return {
        "media": _media_backend(),
        "docs": _docs_backend(),
        "media_bucket_set": bool((settings.GCS_PUBLIC_BUCKET or "").strip()),
        "docs_bucket_set": bool((settings.GCS_PRIVATE_BUCKET or "").strip()),
        "s3_media_bucket_set": bool((_settings().S3_MEDIA_BUCKET or _settings().AWS_S3_BUCKET or "").strip()),
        "s3_docs_bucket_set": bool((_settings().S3_DOCS_BUCKET or _settings().AWS_S3_BUCKET or "").strip()),
        "s3_media_bucket": (_settings().S3_MEDIA_BUCKET or _settings().AWS_S3_BUCKET or "").strip() or None,
        "s3_docs_bucket": (_settings().S3_DOCS_BUCKET or _settings().AWS_S3_BUCKET or "").strip() or None,
        "aws_region": _settings().AWS_REGION,
        "local_upload_dir": os.path.abspath(settings.UPLOAD_DIR),
    }


def update_media(user_id: str, storage_key: str, data: bytes, content_type: str) -> dict:
    """Replace a Sayvors-owned photo while retaining its storage key."""
    safe_type = (
        content_type if content_type.startswith(("image/", "video/"))
        else "application/octet-stream"
    )
    if _media_backend() == "s3":
        from integrations.storage import s3

        key = storage_key
        if key.startswith(f"media/{user_id}/"):
            key = key[len("media/"):]
        return s3.update("media", key, data, safe_type)
    if _media_backend() == "gcs":
        settings = _settings()
        key = storage_key
        if key.startswith(f"media/{user_id}/"):
            key = key[len("media/"):]
        if not key.startswith(f"{user_id}/"):
            key = f"{user_id}/{Path(key).name}"
        full_key = f"media/{key}"
        bucket = settings.GCS_PUBLIC_BUCKET.strip()
        _gcs_client().bucket(bucket).blob(full_key).upload_from_string(data, content_type=safe_type)
        return {"operation": "update", "bucket": bucket, "key": full_key,
                "url": _public_url(bucket, full_key), "size": len(data),
                "content_type": safe_type}
    target = _local_media_root() / user_id / Path(storage_key).name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return {"operation": "update", "key": f"{user_id}/{target.name}",
            "size": len(data), "content_type": safe_type}


def get_media(user_id: str, storage_key: str) -> bytes:
    """Read a media object from its configured backend."""
    if _media_backend() == "s3":
        from integrations.storage import s3

        key = storage_key
        if key.startswith(f"media/{user_id}/"):
            key = key[len("media/"):]
        return s3.get("media", key)
    if _media_backend() == "gcs":
        key = storage_key
        if key.startswith(f"media/{user_id}/"):
            key = key[len("media/"):]
        if not key.startswith(f"{user_id}/"):
            key = f"{user_id}/{Path(key).name}"
        try:
            return _gcs_client().bucket(_settings().GCS_PUBLIC_BUCKET.strip()).blob(
                f"media/{key}"
            ).download_as_bytes()
        except Exception as e:
            if e.__class__.__name__ in {"NotFound", "NoSuchKey"}:
                raise FileNotFoundError(storage_key) from e
            raise
    target = _local_media_root() / user_id / Path(storage_key).name
    if not target.exists():
        raise FileNotFoundError(storage_key)
    return target.read_bytes()


def list_media_objects(user_id: str) -> dict:
    """List only one tenant's media objects with storage metadata."""
    if _media_backend() == "s3":
        from integrations.storage import s3

        return s3.list_objects("media", user_id)
    if _media_backend() == "gcs":
        bucket = _settings().GCS_PUBLIC_BUCKET.strip()
        blobs = _gcs_client().bucket(bucket).list_blobs(prefix=f"media/{user_id}/")
        items = [{"key": b.name.removeprefix(f"media/{user_id}/"), "size": b.size,
                  "etag": b.etag, "last_modified": b.updated.isoformat() if b.updated else None,
                  "url": b.public_url} for b in blobs]
        return {"bucket": bucket, "prefix": user_id, "count": len(items), "items": items}
    root = _local_media_root() / user_id
    items = (
        [{"key": p.name, "size": p.stat().st_size, "url": None}
         for p in root.iterdir() if p.is_file()]
        if root.exists() else []
    )
    return {"bucket": None, "prefix": user_id, "count": len(items), "items": items}
