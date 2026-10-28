"""Regression tests for the admin audit middleware.

Two defects from the 2026-10-25 pass (INS-1, INS-2):
- the middleware was registered twice, so every admin action wrote two rows;
- a failed audit write logged at debug, hiding a dead audit trail.
"""
import logging

import pytest
from starlette.requests import Request
from starlette.responses import Response


def _request(path: str = "/api/v1/admin/operators") -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 80),
        }
    )


def test_admin_audit_middleware_registered_exactly_once():
    """INS-1: a second registration doubles every row in admin_audit_logs."""
    from app.main import AdminAuditMiddleware, app

    registered = [
        mw for mw in app.user_middleware if getattr(mw, "cls", None) is AdminAuditMiddleware
    ]
    assert len(registered) == 1, f"AdminAuditMiddleware registered {len(registered)} times"


@pytest.mark.asyncio
async def test_failed_audit_write_logs_warning_with_path(monkeypatch, caplog):
    """INS-2: a dead audit trail must be visible at default log levels."""
    from app import database as db_module
    from app.main import AdminAuditMiddleware

    def exploding_session(*_args, **_kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(db_module, "async_session", exploding_session)

    async def call_next(_request: Request) -> Response:
        return Response(status_code=200)

    middleware = AdminAuditMiddleware(app=None)
    request = _request()

    with caplog.at_level(logging.WARNING, logger="app.main"):
        response = await middleware.dispatch(request, call_next)

    # The request must still succeed: auditing is best-effort by design.
    assert response.status_code == 200

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "audit failure was not logged at warning level"
    message = warnings[0].getMessage()
    assert "/api/v1/admin/operators" in message
    assert "database unavailable" in message


@pytest.mark.asyncio
async def test_non_admin_path_is_not_audited(monkeypatch, caplog):
    """Guard against the middleware widening its scope while being touched."""
    from app import database as db_module
    from app.main import AdminAuditMiddleware

    def exploding_session(*_args, **_kwargs):
        raise AssertionError("audit must not run for non-admin paths")

    monkeypatch.setattr(db_module, "async_session", exploding_session)

    async def call_next(_request: Request) -> Response:
        return Response(status_code=200)

    middleware = AdminAuditMiddleware(app=None)
    with caplog.at_level(logging.WARNING, logger="app.main"):
        response = await middleware.dispatch(_request("/api/v1/public/health"), call_next)

    assert response.status_code == 200
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
