"""Slash handling must never emit a redirect.

Behind the dev tunnel the API answers the "wrong" slash form with a 307 to an
absolute URL built from the Host header, which sends the browser to
https://localhost:8000/... and silently empties pages that fetch a list.
These tests pin the no-redirect behaviour.
"""
import sys
from pathlib import Path

import pytest  # noqa: F401  (fixtures come from conftest)

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.main import app as fastapi_app

app = fastapi_app


def test_locations_list_does_not_redirect(client):
    r = client.get("/api/v1/locations/", follow_redirects=False)
    assert r.status_code in (200, 401), f"unexpected {r.status_code}"
    assert "location" not in r.headers


def test_channels_list_does_not_redirect(client):
    r = client.get("/api/v1/channels/?limit=100", follow_redirects=False)
    assert r.status_code in (200, 401), f"unexpected {r.status_code}"
    assert "location" not in r.headers


def test_groups_does_not_redirect(client):
    r = client.get("/api/v1/locations/groups", follow_redirects=False)
    assert r.status_code in (200, 401), f"unexpected {r.status_code}"
    assert "location" not in r.headers


def test_group_detail_does_not_redirect(client):
    # /groups/{id} exists as PATCH/DELETE only, so GET is 405 rather than 404.
    # Either is fine — what matters is that no redirect is emitted, since a 307
    # here is what silently breaks the page through the tunnel.
    r = client.get("/api/v1/locations/groups/abc123", follow_redirects=False)
    assert r.status_code in (200, 404, 405), f"unexpected {r.status_code}"
    assert "location" not in r.headers


def test_health_is_not_rewritten(client):
    # /health lives outside /api/v1 and is declared without a slash. Appending
    # one would turn a working health check into a 307.
    r = client.get("/health", follow_redirects=False)
    assert r.status_code == 200, f"unexpected {r.status_code}"
    assert r.json() == {"status": "ok"}
    assert "location" not in r.headers


def test_openapi_is_not_rewritten(client):
    r = client.get("/openapi.json", follow_redirects=False)
    assert r.status_code == 200, f"unexpected {r.status_code}"
    assert "location" not in r.headers


def test_genuine_404_still_404s(client):
    # The rewrite must not invent routes: an unknown path has no slash variant
    # either, so it must stay a 404 rather than 200.
    assert client.get("/api/v1/definitely-not-a-route").status_code == 404
    assert client.get("/api/v1/definitely-not-a-route/").status_code == 404


def test_deep_paths_are_not_rewritten(client):
    # A four-segment /api/v1 path is a real route shape; rewriting it would
    # turn a clean 404/405 into a redirect.
    r = client.get("/api/v1/locations/groups/abc/def", follow_redirects=False)
    assert r.status_code in (404, 405), f"unexpected {r.status_code}"
    assert "location" not in r.headers
