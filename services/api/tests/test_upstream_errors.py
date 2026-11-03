"""Upstream errors log in full but never reach the client verbatim."""
import logging

from app.core.upstream_errors import DEFAULT_UPSTREAM_DETAIL, upstream_http_error


def test_upstream_error_is_generic_but_logged(caplog):
    exc = RuntimeError("postgresql://admin:secret@internal-db:5432/prod down")
    caplog.set_level(logging.ERROR)

    err = upstream_http_error(exc, context="test provider failed")

    assert err.status_code == 502
    assert err.detail == DEFAULT_UPSTREAM_DETAIL
    assert "postgresql://" not in err.detail
    assert "test provider failed" in caplog.text
    assert "postgresql://" in caplog.text


def test_upstream_error_accepts_a_safe_specific_detail():
    err = upstream_http_error(
        RuntimeError("driver detail"),
        context="test provider failed",
        status_code=503,
        detail="Storage is temporarily unavailable.",
    )
    assert err.status_code == 503
    assert err.detail == "Storage is temporarily unavailable."
