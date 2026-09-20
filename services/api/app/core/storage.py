"""Shared file storage: Google Cloud Storage with local-disk fallback.

Two classes of files, two buckets:
- MEDIA (public): owner photos/videos that go to Google. The provider
  fetches them by URL, so objects are public and put_media returns a
  public https URL.
- DOCS (private): databank uploads, scrapes, exports. Never public;
  workers read them back with get_doc_bytes.

Backend selection per class: GCS bucket setting present -> GCS,
otherwise local disk (UPLOAD_DIR layout, byte-identical to the historic
paths, so existing files keep working with zero migration).

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
    return bool((_settings().GCS_PUBLIC_BUCKET or "").strip())


def docs_configured() -> bool:
    return bool((_settings().GCS_PRIVATE_BUCKET or "").strip())


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
    """Store a media file. Returns (storage_key, public_url)."""
    ext = Path(filename or "").suffix.lower()
    stored = f"{uuid.uuid4().hex}{ext}"
    if media_configured():
        settings = _settings()
        key = f"media/{user_id}/{stored}"
        client = _gcs_client()
        blob = client.bucket(settings.GCS_PUBLIC_BUCKET.strip()).blob(key)
        blob.upload_from_string(data, content_type=content_type or "application/octet-stream")
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


def delete_media(user_id: str, storage_key: str) -> None:
    if media_configured():
        try:
            _gcs_client().bucket(_settings().GCS_PUBLIC_BUCKET.strip()).blob(
                f"media/{user_id}/{storage_key}"
            ).delete()
        except Exception as e:
            logger.debug("GCS media delete failed for %s: %s", storage_key, e)
        return
    try:
        (_local_media_root() / user_id / Path(storage_key).name).unlink(missing_ok=True)
    except Exception as e:
        logger.debug("Local media delete failed for %s: %s", storage_key, e)


# ── docs (private) ────────────────────────────────────────────────

def _doc_key(databank_id: str, filename: str) -> str:
    return f"docs/{databank_id}/{filename}"


def put_doc(databank_id: str, filename: str, data: bytes) -> None:
    if docs_configured():
        settings = _settings()
        _gcs_client().bucket(settings.GCS_PRIVATE_BUCKET.strip()).blob(
            _doc_key(databank_id, filename)
        ).upload_from_string(data, content_type="application/octet-stream")
        return
    path = _local_doc_path(databank_id, filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def get_doc(databank_id: str, filename: str) -> bytes:
    if docs_configured():
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


def delete_doc(databank_id: str, filename: str) -> None:
    if docs_configured():
        try:
            _gcs_client().bucket(_settings().GCS_PRIVATE_BUCKET.strip()).blob(
                _doc_key(databank_id, filename)
            ).delete()
        except Exception as e:
            logger.debug("GCS doc delete failed for %s: %s", filename, e)
        return
    try:
        _local_doc_path(databank_id, filename).unlink(missing_ok=True)
    except Exception as e:
        logger.debug("Local doc delete failed for %s: %s", filename, e)


def delete_bank(databank_id: str) -> None:
    """Remove every file of one databank (best effort)."""
    if docs_configured():
        try:
            bucket = _gcs_client().bucket(_settings().GCS_PRIVATE_BUCKET.strip())
            for blob in bucket.list_blobs(prefix=_doc_key(databank_id, "")):
                try:
                    blob.delete()
                except Exception:
                    pass
        except Exception as e:
            logger.debug("GCS bank delete failed for %s: %s", databank_id, e)
        return
    try:
        import shutil

        shutil.rmtree(
            Path(_settings().UPLOAD_DIR) / databank_id, ignore_errors=True
        )
    except Exception:
        pass


def local_media_url(base_url: str, user_id: str, storage_key: str) -> str:
    settings = _settings()
    return (
        f"{base_url.rstrip('/')}{settings.MEDIA_PUBLIC_PATH}/{user_id}/{storage_key}"
    )


def storage_status() -> dict:
    """For health/debug endpoints: which backend each class uses (no secrets)."""
    settings = _settings()
    return {
        "media": "gcs" if media_configured() else "local",
        "docs": "gcs" if docs_configured() else "local",
        "media_bucket_set": bool((settings.GCS_PUBLIC_BUCKET or "").strip()),
        "docs_bucket_set": bool((settings.GCS_PRIVATE_BUCKET or "").strip()),
        "local_upload_dir": os.path.abspath(settings.UPLOAD_DIR),
    }
