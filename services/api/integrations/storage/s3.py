"""S3 storage backend for media (public) and docs (private).

Backend selection in app/core/storage.py prefers S3 when the matching
bucket env var is set, falls back to GCS, then local disk. This module
lazily builds a boto3 client so the package imports cleanly without
boto3 installed (local-only deployments).

Env vars (all optional; empty = local disk for that class):
- AWS_S3_BUCKET          — shared default bucket for both classes
- S3_MEDIA_BUCKET        — overrides AWS_S3_BUCKET for public media
- S3_DOCS_BUCKET         — overrides AWS_S3_BUCKET for private docs
- AWS_REGION             — default eu-north-1
- AWS_S3_ENDPOINT_URL    — optional S3-compatible override (MinIO etc.)
- S3_MEDIA_PUBLIC_BASE_URL — optional CDN/custom domain for media URLs

Auth: standard AWS credential chain (env vars AWS_ACCESS_KEY_ID /
AWS_SECRET_ACCESS_KEY, IAM role, or ~/.aws/credentials). Never commit
secrets — mount them via the platform secret store.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_client: Any = None


def _settings():
    from app.config import settings

    return settings


def _bucket(purpose: str) -> str:
    """Resolve the bucket for a purpose: S3_<PURPOSE>_BUCKET > AWS_S3_BUCKET.

    AWS_S3_BUCKET is a fallback only for public media. Private docs require
    their own explicit S3_DOCS_BUCKET — never reuse the media bucket for
    private documents.
    """
    s = _settings()
    if purpose == "media":
        return s.S3_MEDIA_BUCKET or s.AWS_S3_BUCKET or ""
    if purpose == "docs":
        return s.S3_DOCS_BUCKET or ""
    raise ValueError(f"unknown storage purpose: {purpose}")


def configured(purpose: str) -> bool:
    """True when S3 is configured for the given purpose."""
    return bool(_bucket(purpose).strip())


def _client_lazy() -> Any:
    global _client
    if _client is not None:
        # _client may be a boto3 client (production) or a factory callable
        # (test mocks set s3._client = lambda: client). Resolve once and cache.
        if callable(_client):
            _client = _client()
        return _client
    try:
        import boto3
        from botocore.client import Config
    except ImportError as e:
        raise RuntimeError(
            "boto3 is not installed; cannot use S3 backend. "
            "pip install boto3 botocore"
        ) from e

    s = _settings()
    kwargs: dict[str, Any] = {
        "region_name": s.AWS_REGION or "eu-north-1",
    }
    if s.AWS_S3_ENDPOINT_URL and s.AWS_S3_ENDPOINT_URL.strip():
        kwargs["endpoint_url"] = s.AWS_S3_ENDPOINT_URL.strip()
    _client = boto3.client("s3", config=Config(retries={"max_attempts": 3}), **kwargs)
    return _client


def _public_url(bucket: str, key: str) -> str:
    s = _settings()
    base = (s.S3_MEDIA_PUBLIC_BASE_URL or "").strip()
    if base:
        return f"{base.rstrip('/')}/{key.lstrip('/')}"
    if s.AWS_S3_ENDPOINT_URL and s.AWS_S3_ENDPOINT_URL.strip():
        return f"{s.AWS_S3_ENDPOINT_URL.rstrip('/')}/{bucket}/{key}"
    return f"https://{bucket}.s3.{s.AWS_REGION or 'eu-north-1'}.amazonaws.com/{key}"


def _s3_error_message(exc: Any) -> str:
    """Extract an actionable AWS error code/message from a botocore ClientError."""
    try:
        resp = exc.response.get("Error", {}) if hasattr(exc, "response") else {}
        code = resp.get("Code", "")
        msg = resp.get("Message", "")
        if code:
            return f"{code}: {msg}" if msg else code
        return str(exc)
    except Exception:
        return str(exc)


# ── put ──────────────────────────────────────────────────────────────

def put(purpose: str, key: str, data: bytes, content_type: str) -> dict[str, Any]:
    """Upload an object. Returns metadata dict (storage.py reads url/key/etc.).

    The object is stored at `{purpose}/{key}` so media and docs never collide
    in the same bucket. The returned key includes the purpose prefix.
    """
    bucket = _bucket(purpose)
    if not bucket:
        raise RuntimeError(f"S3 bucket not configured for purpose '{purpose}'")
    client = _client_lazy()
    full_key = f"{purpose}/{key}"
    try:
        resp = client.put_object(
            Bucket=bucket,
            Key=full_key,
            Body=data,
            ContentType=content_type,
        )
    except Exception as exc:
        msg = _s3_error_message(exc)
        logger.error("S3 put failed for %s/%s: %s", bucket, full_key, msg)
        raise RuntimeError(msg) from exc

    return {
        "operation": "upload",
        "bucket": bucket,
        "key": full_key,
        "url": _public_url(bucket, full_key),
        "content_type": content_type,
        "size": len(data),
        "etag": (resp.get("ETag") or "").strip('"'),
        "version_id": resp.get("VersionId"),
    }


# ── get ──────────────────────────────────────────────────────────────

def get(purpose: str, key: str) -> bytes:
    """Download an object's bytes. Raises FileNotFoundError when missing."""
    bucket = _bucket(purpose)
    if not bucket:
        raise RuntimeError(f"S3 bucket not configured for purpose '{purpose}'")
    client = _client_lazy()
    full_key = f"{purpose}/{key}"
    try:
        resp = client.get_object(Bucket=bucket, Key=full_key)
    except Exception as exc:
        if _is_not_found(exc):
            raise FileNotFoundError(f"S3 object not found: {purpose}/{key}") from exc
        msg = _s3_error_message(exc)
        logger.error("S3 get failed for %s/%s: %s", bucket, full_key, msg)
        raise RuntimeError(msg) from exc

    body = resp["Body"]
    data = body.read()
    try:
        body.close()
    except Exception:
        pass
    return data


def get_with_metadata(purpose: str, key: str) -> dict[str, Any]:
    """Download bytes plus backend metadata (size, etag, content_type, etc.)."""
    bucket = _bucket(purpose)
    if not bucket:
        raise RuntimeError(f"S3 bucket not configured for purpose '{purpose}'")
    client = _client_lazy()
    full_key = f"{purpose}/{key}"
    try:
        resp = client.get_object(Bucket=bucket, Key=full_key)
    except Exception as exc:
        if _is_not_found(exc):
            raise FileNotFoundError(f"S3 object not found: {purpose}/{key}") from exc
        msg = _s3_error_message(exc)
        logger.error("S3 get_with_metadata failed for %s/%s: %s", bucket, full_key, msg)
        raise RuntimeError(msg) from exc

    body = resp["Body"]
    data = body.read()
    try:
        body.close()
    except Exception:
        pass
    return {
        "content": data,
        "bucket": bucket,
        "key": full_key,
        "operation": "download",
        "size": resp.get("ContentLength", len(data)),
        "content_type": resp.get("ContentType", "application/octet-stream"),
        "etag": (resp.get("ETag") or "").strip('"'),
        "version_id": resp.get("VersionId"),
        "last_modified": (
            resp["LastModified"].isoformat() if resp.get("LastModified") else None
        ),
    }


# ── delete ───────────────────────────────────────────────────────────

def delete(purpose: str, key: str) -> dict[str, Any]:
    """Delete one object. Returns {"deleted": True, ...}."""
    bucket = _bucket(purpose)
    if not bucket:
        raise RuntimeError(f"S3 bucket not configured for purpose '{purpose}'")
    client = _client_lazy()
    full_key = f"{purpose}/{key}"
    try:
        client.delete_object(Bucket=bucket, Key=full_key)
    except Exception as exc:
        msg = _s3_error_message(exc)
        logger.error("S3 delete failed for %s/%s: %s", bucket, full_key, msg)
        raise RuntimeError(msg) from exc
    return {"deleted": True, "bucket": bucket, "key": full_key}


# ── update ───────────────────────────────────────────────────────────

def update(purpose: str, key: str, data: bytes, content_type: str) -> dict[str, Any]:
    """Replace an object while retaining its key. Same shape as put."""
    result = put(purpose, key, data, content_type)
    result["operation"] = "update"
    return result


# ── head ─────────────────────────────────────────────────────────────

def head(purpose: str, key: str) -> dict[str, Any]:
    """Object metadata without downloading the body."""
    bucket = _bucket(purpose)
    if not bucket:
        raise RuntimeError(f"S3 bucket not configured for purpose '{purpose}'")
    client = _client_lazy()
    full_key = f"{purpose}/{key}"
    try:
        resp = client.head_object(Bucket=bucket, Key=full_key)
    except Exception as exc:
        if _is_not_found(exc):
            raise FileNotFoundError(f"S3 object not found: {purpose}/{key}") from exc
        msg = _s3_error_message(exc)
        logger.error("S3 head failed for %s/%s: %s", bucket, full_key, msg)
        raise RuntimeError(msg) from exc
    return {
        "operation": "head",
        "bucket": bucket,
        "key": full_key,
        "url": _public_url(bucket, full_key),
        "size": resp.get("ContentLength", 0),
        "content_type": resp.get("ContentType", "application/octet-stream"),
        "etag": (resp.get("ETag") or "").strip('"'),
        "last_modified": (
            resp["LastModified"].isoformat() if resp.get("LastModified") else None
        ),
    }


# ── list ─────────────────────────────────────────────────────────────

def list_objects(purpose: str, prefix: str) -> dict[str, Any]:
    """List objects under a prefix. Returns count + items."""
    bucket = _bucket(purpose)
    if not bucket:
        raise RuntimeError(f"S3 bucket not configured for purpose '{purpose}'")
    client = _client_lazy()
    full_prefix = f"{purpose}/{prefix}"
    try:
        paginator = client.get_paginator("list_objects_v2")
        items: list[dict[str, Any]] = []
        for page in paginator.paginate(Bucket=bucket, Prefix=full_prefix):
            for obj in page.get("Contents", []):
                items.append(
                    {
                        "key": obj["Key"],
                        "size": obj.get("Size", 0),
                        "etag": (obj.get("ETag") or "").strip('"'),
                        "last_modified": (
                            obj["LastModified"].isoformat()
                            if obj.get("LastModified")
                            else None
                        ),
                    }
                )
    except Exception as exc:
        msg = _s3_error_message(exc)
        logger.error("S3 list failed for %s/%s: %s", bucket, full_prefix, msg)
        raise RuntimeError(msg) from exc
    return {"bucket": bucket, "prefix": full_prefix, "count": len(items), "items": items}


# ── delete_prefix ────────────────────────────────────────────────────

def delete_prefix(purpose: str, prefix: str) -> dict[str, Any]:
    """Best-effort delete all objects under a prefix."""
    bucket = _bucket(purpose)
    if not bucket:
        raise RuntimeError(f"S3 bucket not configured for purpose '{purpose}'")
    client = _client_lazy()
    full_prefix = f"{purpose}/{prefix}"
    try:
        listed = list_objects(purpose, prefix)
        objects = listed["items"]
        if not objects:
            return {"deleted": 0, "bucket": bucket, "prefix": full_prefix}
        # S3 delete_objects max 1000 keys per call
        deleted = 0
        for i in range(0, len(objects), 1000):
            chunk = objects[i : i + 1000]
            client.delete_objects(
                Bucket=bucket,
                Delete={
                    "Objects": [{"Key": obj["key"]} for obj in chunk],
                    "Quiet": True,
                },
            )
            deleted += len(chunk)
        return {"deleted": deleted, "bucket": bucket, "prefix": full_prefix}
    except Exception as exc:
        msg = _s3_error_message(exc)
        logger.error("S3 delete_prefix failed for %s/%s: %s", bucket, full_prefix, msg)
        raise RuntimeError(msg) from exc


# ── presign ──────────────────────────────────────────────────────────

def presign_get(purpose: str, key: str, expires_seconds: int = 900) -> str:
    """Generate a time-limited GET URL for a private object."""
    bucket = _bucket(purpose)
    if not bucket:
        raise RuntimeError(f"S3 bucket not configured for purpose '{purpose}'")
    client = _client_lazy()
    full_key = f"{purpose}/{key}"
    try:
        url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": full_key},
            ExpiresIn=max(1, min(expires_seconds, 604800)),
        )
    except Exception as exc:
        msg = _s3_error_message(exc)
        logger.error("S3 presign_get failed for %s/%s: %s", bucket, full_key, msg)
        raise RuntimeError(msg) from exc
    return url


def presign_put(
    purpose: str,
    key: str,
    content_type: str,
    expires_seconds: int = 900,
) -> dict[str, str]:
    """Generate a time-limited PUT URL for direct client-to-S3 upload.

    Returns {"url": ..., "fields": {...}} where fields can be sent as
    multipart form fields alongside the file blob.
    """
    bucket = _bucket(purpose)
    if not bucket:
        raise RuntimeError(f"S3 bucket not configured for purpose '{purpose}'")
    client = _client_lazy()
    full_key = f"{purpose}/{key}"
    try:
        resp = client.generate_presigned_post(
            Bucket=bucket,
            Key=full_key,
            Fields={"Content-Type": content_type},
            Conditions=[
                {"Content-Type": content_type},
                ["content-length-range", 1, 200 * 1024 * 1024],
            ],
            ExpiresIn=max(1, min(expires_seconds, 3600)),
        )
    except Exception as exc:
        msg = _s3_error_message(exc)
        logger.error("S3 presign_put failed for %s/%s: %s", bucket, full_key, msg)
        raise RuntimeError(msg) from exc
    return {"url": resp["url"], "fields": resp["fields"]}


# ── helpers ──────────────────────────────────────────────────────────

def _is_not_found(exc: Any) -> bool:
    try:
        resp = exc.response.get("Error", {}) if hasattr(exc, "response") else {}
        code = resp.get("Code", "")
        return code in {"NoSuchKey", "NoSuchBucket", "404"}
    except Exception:
        return False
