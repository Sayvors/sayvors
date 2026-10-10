"""Regression: Instagram field requests that Meta actually accepts.

Live bug: the profile page 400'd with "(#100) Tried accessing nonexisting
field (account_type)" and showed an empty profile. The same bad field was in
check_eligibility, which runs at connect time - so every discovered Instagram
account was being marked "ineligible" too.

account_type is not a readable field on the IG User node in current Graph
versions, so it must not be requested anywhere.
"""
import httpx
import pytest

from app.modules.channels.meta.providers.base import MetaAPIError
from app.modules.channels.meta.providers.instagram import InstagramAdapter

pytestmark = pytest.mark.asyncio

IG = "17841405822304922"


def _ok(payload, seen):
    async def _inner(self, method, path, token, **kwargs):
        seen.append(kwargs.get("params", {}).get("fields"))
        return httpx.Response(200, json=payload)

    return _inner


def _reject_unknown_field_then_ok(payload, seen):
    """Simulate Meta rejecting an OPTIONAL field, the way it did for
    account_type: the first (full-field) read fails, the minimal one works.

    The real `_graph` raises MetaAPIError on a non-2xx, so the fake must too -
    returning a 400 response here would never trigger the fallback.
    """

    async def _inner(self, method, path, token, **kwargs):
        fields = kwargs.get("params", {}).get("fields", "")
        seen.append(fields)
        if "biography" in fields:
            raise MetaAPIError(
                "(#100) Tried accessing nonexisting field (biography)", 400
            )
        return httpx.Response(200, json=payload)

    return _inner


def _reject_account_type(payload):
    """Eligility probe that fails if anyone re-adds account_type."""

    async def _inner(self, method, path, token, **kwargs):
        fields = kwargs.get("params", {}).get("fields", "")
        if "account_type" in fields:
            raise MetaAPIError(
                "(#100) Tried accessing nonexisting field (account_type)", 400
            )
        return httpx.Response(200, json=payload)

    return _inner


async def test_profile_never_requests_account_type(monkeypatch):
    seen: list = []
    monkeypatch.setattr(
        InstagramAdapter,
        "_graph",
        _ok({"id": IG, "username": "sayvors", "name": "Sayvors"}, seen),
    )

    await InstagramAdapter().get_business_profile(IG, "t")

    assert "account_type" not in seen[0]
    for field in ("username", "name", "biography", "website", "followers_count"):
        assert field in seen[0]


async def test_eligibility_never_requests_account_type(monkeypatch):
    seen: list = []
    monkeypatch.setattr(
        InstagramAdapter,
        "_graph",
        _ok({"id": IG, "username": "sayvors", "media_count": 12}, seen),
    )

    ok, detail = await InstagramAdapter().check_eligibility(IG, "t")

    assert "account_type" not in seen[0]
    assert ok is True
    assert "sayvors" in detail


async def test_eligibility_accepts_a_readable_account(monkeypatch):
    """The live bug: a readable Business account was marked ineligible because
    its (never-returned) account_type made the request fail."""
    monkeypatch.setattr(
        InstagramAdapter,
        "_graph",
        _reject_account_type({"id": IG, "username": "sayvors", "media_count": 12}),
    )

    ok, detail = await InstagramAdapter().check_eligibility(IG, "t")

    assert ok is True
    assert "eligible" in detail


async def test_eligibility_rejects_an_unreadable_account(monkeypatch):
    async def _empty(self, method, path, token, **kwargs):
        return httpx.Response(200, json={})

    monkeypatch.setattr(InstagramAdapter, "_graph", _empty)

    ok, detail = await InstagramAdapter().check_eligibility(IG, "t")

    assert ok is False
    assert "private" in detail or "personal" in detail


async def test_eligibility_reports_graph_failure(monkeypatch):
    async def _boom(self, method, path, token, **kwargs):
        raise MetaAPIError("nope", 401)

    monkeypatch.setattr(InstagramAdapter, "_graph", _boom)

    ok, detail = await InstagramAdapter().check_eligibility(IG, "t")

    assert ok is False
    assert "401" in detail


async def test_profile_degrades_to_minimal_fields_when_meta_rejects_one(monkeypatch):
    """A future rejected optional field must not blank the whole profile."""
    seen: list = []
    monkeypatch.setattr(
        InstagramAdapter,
        "_graph",
        _reject_unknown_field_then_ok(
            {"id": IG, "username": "sayvors", "name": "Sayvors"}, seen
        ),
    )

    out = await InstagramAdapter().get_business_profile(IG, "t")

    assert len(seen) == 2
    assert out["username"] == "sayvors"
    # Counters still normalised on the degraded path.
    assert out["followers_count"] == 0


async def test_profile_does_not_swallow_a_real_failure(monkeypatch):
    """The fallback must not turn a genuine error into an empty profile."""
    calls = {"n": 0}

    async def _boom(self, method, path, token, **kwargs):
        calls["n"] += 1
        raise MetaAPIError("token revoked", 401)

    monkeypatch.setattr(InstagramAdapter, "_graph", _boom)

    with pytest.raises(MetaAPIError):
        await InstagramAdapter().get_business_profile(IG, "t")
    # Both attempts fail, and the error surfaces.
    assert calls["n"] == 2