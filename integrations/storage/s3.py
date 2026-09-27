"""Small S3-compatible object-storage adapter.

Uses boto3's normal credential chain (environment, instance/task role, or
shared credentials). Media objects are addressed by a public URL; private
objects are always read through the SDK. Bucket policy/public access is the
operator's responsibility; this adapter never adds a public ACL.
"""
from __future__ import annotations

import logging
from urllib.parse import quote

logger = logging.getLogger(__name__)


def _settings():
    from app.config import settings

    return settings


def _bucket(kind: str) -> str:
    settings = _settings()
    if kind == "media":
        return (settings.S3_MEDIA_BUCKET or settings.AWS_S3_BUCKET or "").strip()
    # Private documents must not silently share the potentially public media
    # bucket. Configure a distinct S3_DOCS_BUCKET when moving docs to S3.
    return (settings.S3_DOCS_BUCKET or "").strip()


def configured(kind: str) -> bool:
    return bool(_bucket(kind))


def _client():
    settings = _settings()
    try:
        import boto3
    except ImportError as e:
        raise RuntimeError("boto3 is not installed; cannot use S3 storage.") from e

    options = {"region_name": settings.AWS_REGION or None}
    if settings.AWS_S3_ENDPOINT_URL:
        options["endpoint_url"] = settings.AWS_S3_ENDPOINT_URL.rstrip("/")
    # Do not pass credentials here: boto3 resolves AWS env vars, workload roles,
    # and standard shared-credential providers without copying secrets to logs.
    try:
        return boto3.client("s3", **options)
    except Exception as e:
        code = str(getattr(e, "response", {}).get("Error", {}).get("Code", type(e).__name__))
        raise RuntimeError(f"Could not initialize S3 client ({code}).") from e


def object_key(kind: str, key: str) -> str:
    prefix = "media" if kind == "media" else "docs"
    return f"{prefix}/{key.lstrip('/')}"


def public_url(key: str) -> str:
    settings = _settings()
    bucket = _bucket("media")
    encoded_key = quote(key.lstrip("/"), safe="/")
    custom = (settings.S3_MEDIA_PUBLIC_BASE_URL or "").rstrip("/")
    if custom:
        return f"{custom}/{encoded_key}"
    region = settings.AWS_REGION or "us-east-1"
    if settings.AWS_S3_ENDPOINT_URL:
        endpoint = settings.AWS_S3_ENDPOINT_URL.rstrip("/")
        return f"{endpoint}/{quote(bucket, safe='')}/{encoded_key}"
    return f"https://{bucket}.s3.{region}.amazonaws.com/{encoded_key}"


def put(kind: str, key: str, data: bytes, content_type: str) -> dict:
    bucket = _bucket(kind)
    if not bucket:
        raise RuntimeError(f"S3 bucket is not configured for {kind} storage.")
    args = {
        "Bucket": bucket,
        "Key": object_key(kind, key),
        "Body": data,
        "ContentType": content_type,
    }
    try:
        response = _client().put_object(**args)
    except Exception as e:
        error = getattr(e, "response", {}).get("Error", {})
        code = str(error.get("Code") or type(e).__name__)
        message = str(error.get("Message") or "")[:180]
        # Never log the boto exception/traceback; provider exceptions may
        # contain signed request details. Bucket/key/code are sufficient.
        logger.error("S3 upload failed bucket=%s key=%s code=%s", bucket, args["Key"], code)
        if code in {"NoCredentialsError", "PartialCredentialsError", "CredentialRetrievalError"}:
            raise RuntimeError(
                "AWS credentials are not available to this API process. Set "
                "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in the same shell "
                "that starts Uvicorn, then restart it."
            ) from e
        raise RuntimeError(
            f"S3 upload failed ({code})" + (f": {message}" if message else "")
        ) from e
    return {
        "operation": "upload",
        "bucket": bucket,
        "key": args["Key"],
        "url": public_url(args["Key"]) if kind == "media" else None,
        "content_type": content_type,
        "size": len(data),
        "etag": str(response.get("ETag", "")).strip('"') or None,
        "version_id": response.get("VersionId"),
    }


def get(kind: str, key: str) -> bytes:
    bucket = _bucket(kind)
    if not bucket:
        raise RuntimeError(f"S3 bucket is not configured for {kind} storage.")
    try:
        response = _client().get_object(Bucket=bucket, Key=object_key(kind, key))
    except Exception as e:
        code = str(getattr(e, "response", {}).get("Error", {}).get("Code", ""))
        if code in {"NoSuchKey", "NoSuchObject", "404", "NotFound"}:
            raise FileNotFoundError(key) from e
        raise
    body = response["Body"]
    try:
        return body.read()
    finally:
        close = getattr(body, "close", None)
        if close:
            close()


def get_with_metadata(kind: str, key: str) -> dict:
    """Download an object and include S3 response metadata."""
    bucket = _bucket(kind)
    if not bucket:
        raise RuntimeError(f"S3 bucket is not configured for {kind} storage.")
    try:
        response = _client().get_object(Bucket=bucket, Key=object_key(kind, key))
    except Exception as e:
        code = str(getattr(e, "response", {}).get("Error", {}).get("Code", ""))
        if code in {"NoSuchKey", "NoSuchObject", "404", "NotFound"}:
            raise FileNotFoundError(key) from e
        raise
    body = response["Body"]
    try:
        content = body.read()
    finally:
        close = getattr(body, "close", None)
        if close:
            close()
    return {
        "operation": "download",
        "content": content,
        "bucket": bucket,
        "key": object_key(kind, key),
        "size": response.get("ContentLength", len(content)),
        "content_type": response.get("ContentType"),
        "etag": str(response.get("ETag", "")).strip('"') or None,
        "last_modified": response.get("LastModified").isoformat()
        if response.get("LastModified") else None,
        "version_id": response.get("VersionId"),
    }


def update(kind: str, key: str, data: bytes, content_type: str) -> dict:
    """Overwrite an object and identify the operation as an update."""
    result = put(kind, key, data, content_type)
    result["operation"] = "update"
    return result


def delete(kind: str, key: str) -> dict:
    bucket = _bucket(kind)
    if not bucket:
        raise RuntimeError(f"S3 bucket is not configured for {kind} storage.")
    target = object_key(kind, key)
    response = _client().delete_object(Bucket=bucket, Key=target)
    return {
        "operation": "delete",
        "deleted": True,
        "bucket": bucket,
        "key": target,
        "version_id": response.get("VersionId"),
        "delete_marker": response.get("DeleteMarker"),
    }


def delete_prefix(kind: str, prefix: str) -> dict:
    bucket = _bucket(kind)
    if not bucket:
        raise RuntimeError(f"S3 bucket is not configured for {kind} storage.")
    client = _client()
    full_prefix = object_key(kind, prefix).rstrip("/") + "/"
    paginator = client.get_paginator("list_objects_v2")
    deleted = 0
    for page in paginator.paginate(Bucket=bucket, Prefix=full_prefix):
        objects = [{"Key": item["Key"]} for item in page.get("Contents", [])]
        if objects:
            response = client.delete_objects(Bucket=bucket, Delete={"Objects": objects})
            deleted += len(response.get("Deleted", []))
    return {"deleted": deleted, "bucket": bucket, "prefix": full_prefix}


def list_keys(kind: str, prefix: str = "") -> list[str]:
    bucket = _bucket(kind)
    if not bucket:
        raise RuntimeError(f"S3 bucket is not configured for {kind} storage.")
    client = _client()
    full_prefix = object_key(kind, prefix) if prefix else ("media/" if kind == "media" else "docs/")
    paginator = client.get_paginator("list_objects_v2")
    out: list[str] = []
    namespace = "media/" if kind == "media" else "docs/"
    for page in paginator.paginate(Bucket=bucket, Prefix=full_prefix):
        for item in page.get("Contents", []):
            key = item.get("Key", "")
            if key.startswith(namespace):
                out.append(key[len(namespace):])
    return out


def list_objects(kind: str, prefix: str = "") -> dict:
    """List object keys and metadata under a logical prefix."""
    bucket = _bucket(kind)
    if not bucket:
        raise RuntimeError(f"S3 bucket is not configured for {kind} storage.")
    client = _client()
    namespace = "media/" if kind == "media" else "docs/"
    full_prefix = object_key(kind, prefix) if prefix else namespace
    paginator = client.get_paginator("list_objects_v2")
    items = []
    for page in paginator.paginate(Bucket=bucket, Prefix=full_prefix):
        for obj in page.get("Contents", []):
            key = str(obj.get("Key") or "")
            items.append({
                "key": key[len(namespace):] if key.startswith(namespace) else key,
                "size": obj.get("Size"),
                "etag": str(obj.get("ETag", "")).strip('"') or None,
                "last_modified": obj.get("LastModified").isoformat()
                if obj.get("LastModified") else None,
                "url": public_url(key) if kind == "media" else None,
            })
    return {"operation": "list", "bucket": bucket, "prefix": prefix,
            "count": len(items), "items": items}


def head(kind: str, key: str) -> dict:
    """Return object metadata without downloading its body."""
    bucket = _bucket(kind)
    if not bucket:
        raise RuntimeError(f"S3 bucket is not configured for {kind} storage.")
    response = _client().head_object(Bucket=bucket, Key=object_key(kind, key))
    return {
        "operation": "head",
        "bucket": bucket,
        "key": object_key(kind, key),
        "size": response.get("ContentLength"),
        "content_type": response.get("ContentType"),
        "etag": str(response.get("ETag", "")).strip('"') or None,
        "last_modified": response.get("LastModified").isoformat()
        if response.get("LastModified") else None,
        "version_id": response.get("VersionId"),
        "url": public_url(object_key(kind, key)) if kind == "media" else None,
    }


def presign_get(kind: str, key: str, expires_seconds: int = 900) -> str:
    """Create a short-lived download URL (primarily for private documents)."""
    bucket = _bucket(kind)
    if not bucket:
        raise RuntimeError(f"S3 bucket is not configured for {kind} storage.")
    return _client().generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": object_key(kind, key)},
        ExpiresIn=max(1, min(int(expires_seconds), 604800)),
    )
