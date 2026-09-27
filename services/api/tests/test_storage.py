"""Shared file storage: local backend roundtrips + GCS selection logic.

GCS itself is never touched here (no credentials in tests): selection is
verified by flags, and the google-cloud-storage import stays lazy so this
suite passes without the package installed.
"""
import pytest

from app.config import settings
from app.core import storage


@pytest.fixture
def _dirs(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "MEDIA_DIR", str(tmp_path / "uploads" / "media"))
    monkeypatch.setattr(settings, "GCS_PUBLIC_BUCKET", "")
    monkeypatch.setattr(settings, "GCS_PRIVATE_BUCKET", "")
    monkeypatch.setattr(settings, "AWS_S3_BUCKET", "")
    monkeypatch.setattr(settings, "S3_MEDIA_BUCKET", "")
    monkeypatch.setattr(settings, "S3_DOCS_BUCKET", "")
    return tmp_path


def test_media_roundtrip_local(_dirs, tmp_path):
    key, public_url = storage.put_media("u1", "shop.jpg", b"data-bytes", "image/jpeg")
    assert public_url == ""  # local backend: caller builds origin URL
    assert (tmp_path / "uploads" / "media" / "u1" / key).read_bytes() == b"data-bytes"
    url = storage.local_media_url("https://api.example.com/", "u1", key)
    assert url == f"https://api.example.com/media-files/u1/{key}"
    assert key.endswith(".jpg")
    storage.delete_media("u1", key)
    assert not (tmp_path / "uploads" / "media" / "u1" / key).exists()


def test_docs_roundtrip_local(_dirs, tmp_path):
    storage.put_doc("bank1", "doc1.txt", b"hello world")
    assert storage.get_doc("bank1", "doc1.txt") == b"hello world"
    # Legacy layout preserved: UPLOAD_DIR/<bank>/<file>, no migration.
    assert (tmp_path / "uploads" / "bank1" / "doc1.txt").exists()
    storage.put_doc("bank1", "doc2.txt", b"second")
    storage.delete_doc("bank1", "doc1.txt")
    with pytest.raises(FileNotFoundError):
        storage.get_doc("bank1", "doc1.txt")
    storage.delete_bank("bank1")
    assert not (tmp_path / "uploads" / "bank1").exists()


def test_get_missing_doc_raises(_dirs):
    with pytest.raises(FileNotFoundError):
        storage.get_doc("no-bank", "nope.txt")


def test_backend_selection(monkeypatch):
    monkeypatch.setattr(settings, "AWS_S3_BUCKET", "")
    monkeypatch.setattr(settings, "S3_MEDIA_BUCKET", "")
    monkeypatch.setattr(settings, "S3_DOCS_BUCKET", "")
    monkeypatch.setattr(settings, "GCS_PUBLIC_BUCKET", "")
    monkeypatch.setattr(settings, "GCS_PRIVATE_BUCKET", "")
    assert storage.media_configured() is False
    assert storage.docs_configured() is False
    monkeypatch.setattr(settings, "GCS_PUBLIC_BUCKET", "sayvors-media")
    monkeypatch.setattr(settings, "GCS_PRIVATE_BUCKET", "sayvors-private")
    assert storage.media_configured() is True
    assert storage.docs_configured() is True
    status = storage.storage_status()
    assert status["media"] == "gcs" and status["docs"] == "gcs"
    assert status["media_bucket_set"] is True and status["docs_bucket_set"] is True


def test_s3_backend_selection(monkeypatch):
    monkeypatch.setattr(settings, "GCS_PUBLIC_BUCKET", "")
    monkeypatch.setattr(settings, "GCS_PRIVATE_BUCKET", "")
    monkeypatch.setattr(settings, "AWS_S3_BUCKET", "sayvorsstorage-221201452822-eu-north-1-an")
    monkeypatch.setattr(settings, "S3_MEDIA_BUCKET", "")
    monkeypatch.setattr(settings, "S3_DOCS_BUCKET", "")
    monkeypatch.setattr(settings, "AWS_REGION", "eu-north-1")

    assert storage.storage_status()["media"] == "s3"
    assert storage.storage_status()["docs"] == "local"
    assert storage.storage_status()["s3_media_bucket"] == "sayvorsstorage-221201452822-eu-north-1-an"
    monkeypatch.setattr(settings, "S3_DOCS_BUCKET", "private-docs")
    assert storage.storage_status()["docs"] == "s3"
    assert storage.storage_status()["s3_docs_bucket"] == "private-docs"


def test_s3_storage_operations_return_metadata(monkeypatch):
    from integrations.storage import s3

    monkeypatch.setattr(settings, "AWS_S3_BUCKET", "bucket-test")
    monkeypatch.setattr(settings, "S3_MEDIA_BUCKET", "")
    monkeypatch.setattr(settings, "S3_DOCS_BUCKET", "private-test")
    monkeypatch.setattr(settings, "AWS_REGION", "eu-north-1")
    monkeypatch.setattr(settings, "AWS_S3_ENDPOINT_URL", "")
    monkeypatch.setattr(settings, "S3_MEDIA_PUBLIC_BASE_URL", "")

    class _Body:
        def read(self):
            return b"downloaded"

        def close(self):
            pass

    class _Client:
        def __init__(self):
            self.puts = []
            self.deletes = []

        def put_object(self, **kwargs):
            self.puts.append(kwargs)
            return {"ETag": '"etag-123"', "VersionId": "v1"}

        def get_object(self, **kwargs):
            return {"Body": _Body(), "ContentLength": 10, "ContentType": "text/plain",
                    "ETag": '"etag-123"', "VersionId": "v1"}

        def delete_object(self, **kwargs):
            self.deletes.append(kwargs)
            return {"VersionId": "v2", "DeleteMarker": True}

        def head_object(self, **kwargs):
            return {"ContentLength": 5, "ContentType": "image/jpeg",
                    "ETag": '"etag-123"', "VersionId": "v1"}

        def get_paginator(self, name):
            class _Paginator:
                def paginate(self, **kwargs):
                    return [{"Contents": [{"Key": "media/u1/image.jpg", "Size": 5,
                                            "ETag": '"etag-123"'}]}]
            return _Paginator()

        def delete_objects(self, **kwargs):
            return {"Deleted": kwargs["Delete"]["Objects"]}

        def generate_presigned_url(self, operation, Params, ExpiresIn):
            return f"https://signed.test/{Params['Key']}?expires={ExpiresIn}"

    client = _Client()
    monkeypatch.setattr(s3, "_client", lambda: client)

    uploaded = s3.put("media", "u1/image.jpg", b"photo", "image/jpeg")
    assert uploaded == {
        "operation": "upload", "bucket": "bucket-test", "key": "media/u1/image.jpg",
        "url": "https://bucket-test.s3.eu-north-1.amazonaws.com/media/u1/image.jpg",
        "content_type": "image/jpeg", "size": 5, "etag": "etag-123",
        "version_id": "v1",
    }
    assert s3.get("docs", "bank1/doc.txt") == b"downloaded"
    downloaded = s3.get_with_metadata("docs", "bank1/doc.txt")
    assert downloaded["content"] == b"downloaded"
    assert downloaded["bucket"] == "private-test"
    assert downloaded["operation"] == "download"
    assert s3.update("media", "u1/image.jpg", b"new", "image/jpeg")["operation"] == "update"
    assert s3.head("media", "u1/image.jpg")["url"].endswith("media/u1/image.jpg")
    assert s3.list_objects("media", "u1")["count"] == 1
    assert s3.presign_get("docs", "bank1/doc.txt", 30).endswith("expires=30")
    assert s3.delete("media", "u1/image.jpg")["deleted"] is True
    assert client.deletes[-1]["Key"] == "media/u1/image.jpg"
    assert s3.delete_prefix("media", "u1")["deleted"] == 1


def test_s3_missing_object_becomes_file_not_found(monkeypatch):
    from integrations.storage import s3

    monkeypatch.setattr(settings, "AWS_S3_BUCKET", "bucket-test")
    monkeypatch.setattr(settings, "S3_MEDIA_BUCKET", "")
    monkeypatch.setattr(settings, "S3_DOCS_BUCKET", "private-test")

    class _Client:
        def get_object(self, **kwargs):
            error = RuntimeError("missing")
            error.response = {"Error": {"Code": "NoSuchKey"}}
            raise error

    monkeypatch.setattr(s3, "_client", lambda: _Client())
    with pytest.raises(FileNotFoundError):
        s3.get("docs", "bank1/missing.txt")


def test_s3_upload_error_reports_actionable_aws_code(monkeypatch):
    from integrations.storage import s3

    monkeypatch.setattr(settings, "AWS_S3_BUCKET", "bucket-test")
    monkeypatch.setattr(settings, "S3_MEDIA_BUCKET", "")

    class _Client:
        def put_object(self, **kwargs):
            error = RuntimeError("put failed")
            error.response = {"Error": {"Code": "InvalidAccessKeyId", "Message": "The AWS Access Key Id you provided does not exist"}}
            raise error

    monkeypatch.setattr(s3, "_client", lambda: _Client())
    with pytest.raises(RuntimeError, match="InvalidAccessKeyId") as exc:
        s3.put("media", "u1/image.jpg", b"x", "image/jpeg")
    assert "does not exist" in str(exc.value)


def test_gcs_without_package_raises_clear_error(monkeypatch):
    """Without google-cloud-storage installed, GCS use fails loudly —
    never silently writes locally instead."""
    monkeypatch.setattr(settings, "AWS_S3_BUCKET", "")
    monkeypatch.setattr(settings, "S3_MEDIA_BUCKET", "")
    monkeypatch.setattr(settings, "GCS_PUBLIC_BUCKET", "sayvors-media")
    try:
        import google.cloud.storage  # noqa: F401

        pytest.skip("google-cloud-storage installed; selection covered above")
    except ImportError:
        with pytest.raises(RuntimeError, match="google-cloud-storage is not installed"):
            storage.put_media("u1", "a.jpg", b"x", "image/jpeg")
