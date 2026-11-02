"""The public API schema/docs surface must not be exposed in production."""
from pathlib import Path

from fastapi import FastAPI

from app.main import _docs_urls


def test_production_disables_all_docs_endpoints():
    assert _docs_urls("production") == {
        "docs_url": None,
        "redoc_url": None,
        "openapi_url": None,
    }


def test_fastapi_accepts_the_production_config_and_serves_no_docs():
    probe = FastAPI(**_docs_urls("production"))
    assert probe.docs_url is None
    assert probe.redoc_url is None
    assert probe.openapi_url is None


def test_non_production_keeps_docs_for_development():
    assert _docs_urls("development") == {}
    assert _docs_urls("staging") == {}


def test_caddy_blocks_metrics_and_docs_at_the_edge():
    caddyfile = Path(__file__).resolve().parents[3] / "deploy" / "Caddyfile"
    text = caddyfile.read_text(encoding="utf-8")
    for path in ("/metrics", "/docs", "/redoc", "/openapi.json"):
        assert path in text
    assert "Strict-Transport-Security" in text
