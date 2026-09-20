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


def test_gcs_without_package_raises_clear_error(monkeypatch):
    """Without google-cloud-storage installed, GCS use fails loudly —
    never silently writes locally instead."""
    monkeypatch.setattr(settings, "GCS_PUBLIC_BUCKET", "sayvors-media")
    try:
        import google.cloud.storage  # noqa: F401

        pytest.skip("google-cloud-storage installed; selection covered above")
    except ImportError:
        with pytest.raises(RuntimeError, match="google-cloud-storage is not installed"):
            storage.put_media("u1", "a.jpg", b"x", "image/jpeg")
