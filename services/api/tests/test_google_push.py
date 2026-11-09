"""Google Pub/Sub push ingress tests.

Covers the three things that must never break: fail-closed verification
(no audience ⇒ 503, bad token ⇒ 403), defensive envelope parsing (a
malformed push is acked, never a retry storm), and the targeted-pull
spawn (indexed listing_key lookup, active channels only, bounded).
"""
import base64
import json

import pytest

from app.modules.channels import google_push
from app.modules.channels.models import Channel


def _envelope(notification: dict, message_id="msg-1") -> bytes:
    data = base64.b64encode(json.dumps(notification).encode()).decode()
    return json.dumps({"message": {"data": data, "messageId": message_id}}).encode()


# ── envelope parsing ─────────────────────────────────────


def test_parse_push_envelope_valid():
    notification = {"notificationType": "NEW_REVIEW", "location": "accounts/a/locations/l1"}
    message_id, parsed = google_push.parse_push_envelope(_envelope(notification))
    assert message_id == "msg-1"
    assert parsed == notification


def test_parse_push_envelope_rejects_garbage():
    for bad in (
        b"not json",
        json.dumps({"no_message": True}).encode(),
        json.dumps({"message": {"data": "!!!not-base64!!!"}}).encode(),
        json.dumps({"message": {"data": base64.b64encode(b"not json").decode()}}).encode(),
        json.dumps({"message": {"data": base64.b64encode(b"[1,2]").decode()}}).encode(),
    ):
        assert google_push.parse_push_envelope(bad) == (None, None)


def test_extract_location_ids_shapes():
    assert google_push.extract_location_ids(
        {"location": "accounts/a/locations/l1"}
    ) == ["l1"]
    assert google_push.extract_location_ids(
        {"review": "accounts/a/locations/l2/reviews/r9"}
    ) == ["l2"]
    assert google_push.extract_location_ids({"locationId": "l3"}) == ["l3"]
    # Both fields pointing at the same location dedup to one pull.
    assert google_push.extract_location_ids(
        {
            "location": "accounts/a/locations/l4",
            "review": "accounts/a/locations/l4/reviews/r",
        }
    ) == ["l4"]
    assert google_push.extract_location_ids({"notificationType": "NEW_REVIEW"}) == []
    assert google_push.extract_location_ids({"location": 123}) == []


# ── OIDC verification ────────────────────────────────────


def test_verify_push_fails_closed_without_audience(monkeypatch):
    monkeypatch.setattr(google_push.settings, "GOOGLE_PUBSUB_PUSH_AUDIENCE", "")
    request = type("R", (), {"headers": {"authorization": "Bearer x"}})()
    assert google_push.verify_push_oidc(request) is False


def test_verify_push_rejects_missing_or_malformed_header(monkeypatch):
    monkeypatch.setattr(google_push.settings, "GOOGLE_PUBSUB_PUSH_AUDIENCE", "aud-1")
    for headers in ({}, {"authorization": "Basic abc"}, {"authorization": "Bearer "}):
        request = type("R", (), {"headers": headers})()
        assert google_push.verify_push_oidc(request) is False


def test_verify_push_accepts_valid_token(monkeypatch):
    monkeypatch.setattr(google_push.settings, "GOOGLE_PUBSUB_PUSH_AUDIENCE", "aud-1")
    monkeypatch.setattr(google_push.settings, "GOOGLE_PUBSUB_PUSH_EMAIL", "sa@project.iam.gserviceaccount.com")

    seen = {}

    def _fake_verify(token, request_obj, audience):
        seen["token"] = token
        seen["audience"] = audience
        return {
            "aud": audience,
            "email": "sa@project.iam.gserviceaccount.com",
            "sub": "1",
        }

    monkeypatch.setattr(google_push, "verify_oauth2_token", _fake_verify)
    request = type(
        "R", (), {"headers": {"authorization": "Bearer good-token"}}
    )()
    assert google_push.verify_push_oidc(request) is True
    assert seen["audience"] == "aud-1"


def test_verify_push_rejects_wrong_identity_and_bad_signature(monkeypatch):
    monkeypatch.setattr(google_push.settings, "GOOGLE_PUBSUB_PUSH_AUDIENCE", "aud-1")
    monkeypatch.setattr(google_push.settings, "GOOGLE_PUBSUB_PUSH_EMAIL", "sa@project.iam.gserviceaccount.com")

    def _claims(email):
        return lambda token, request_obj, audience: {"aud": audience, "email": email}

    # Validly-signed but from a different service account.
    monkeypatch.setattr(google_push, "verify_oauth2_token", _claims("other@evil.iam"))
    request = type("R", (), {"headers": {"authorization": "Bearer t"}})()
    assert google_push.verify_push_oidc(request) is False

    # Cryptographic failure.
    def _raise(token, request_obj, audience):
        raise ValueError("bad signature")

    monkeypatch.setattr(google_push, "verify_oauth2_token", _raise)
    assert google_push.verify_push_oidc(request) is False


# ── targeted pull spawn ──────────────────────────────────


@pytest.mark.asyncio
async def test_trigger_pulls_resolves_by_listing_key_and_skips_inactive(
    db, channel_id, config_id, user_id, other_user_id, monkeypatch
):
    # The fixture channel carries no listing_key — give it one, and add a
    # disconnected twin on the same location owned by a DIFFERENT tenant
    # (the unique constraint is per-user, so two tenants may share a
    # listing) that must NOT be pulled.
    channel = await db.get(Channel, channel_id)
    channel.listing_key = "loc-pushed"
    await db.commit()
    db.add(
        Channel(
            id="test-channel-0000-0000-0000-000000000002",
            user_id=other_user_id,
            platform="google_reviews",
            platform_user_id="demo-acc-123",
            display_name="Disconnected twin",
            status="disconnected",
            listing_key="loc-pushed",
            metadata_json='{"location_id": "loc-pushed"}',
        )
    )
    await db.commit()

    pulled: list[tuple[str, str]] = []

    async def _fake_poll(channel_id_arg, config_id_arg, semaphore):
        pulled.append((channel_id_arg, config_id_arg))

    monkeypatch.setattr("app.modules.channels.reviews_worker._poll_one_channel", _fake_poll)
    spawned = await google_push.trigger_pulls_for_locations(db, ["loc-pushed"])
    # Let the spawned tasks finish so the recorder has run, then tidy up.
    for t in list(google_push._pull_tasks):
        await t
    google_push._pull_tasks.clear()

    assert spawned == 1
    assert pulled == [(channel_id, config_id)]


# ── endpoint ─────────────────────────────────────────────


@pytest.fixture
def _push_env(monkeypatch):
    monkeypatch.setattr(google_push.settings, "GOOGLE_PUBSUB_PUSH_AUDIENCE", "aud-1")
    monkeypatch.setattr(google_push.settings, "GOOGLE_PUBSUB_PUSH_EMAIL", "")
    monkeypatch.setattr(google_push, "verify_push_oidc", lambda request: True)


def test_endpoint_disabled_without_audience(client, monkeypatch):
    monkeypatch.setattr(google_push.settings, "GOOGLE_PUBSUB_PUSH_AUDIENCE", "")
    resp = client.post("/api/v1/channels/google/pubsub", content=b"{}")
    assert resp.status_code == 503


def test_endpoint_rejects_bad_token(client, monkeypatch):
    monkeypatch.setattr(google_push.settings, "GOOGLE_PUBSUB_PUSH_AUDIENCE", "aud-1")
    monkeypatch.setattr(google_push, "verify_push_oidc", lambda request: False)
    resp = client.post(
        "/api/v1/channels/google/pubsub", content=_envelope({"location": "l1"})
    )
    assert resp.status_code == 403


def test_endpoint_rejects_oversized_body(client, _push_env):
    resp = client.post(
        "/api/v1/channels/google/pubsub", content=b"x" * (google_push.PUSH_MAX_BODY_BYTES + 1)
    )
    assert resp.status_code == 413


def test_endpoint_acks_unknown_shape_without_pulling(client, _push_env, monkeypatch):
    called: list[list[str]] = []

    async def _record(db_arg, location_ids):
        called.append(location_ids)
        return 0

    monkeypatch.setattr(google_push, "trigger_pulls_for_locations", _record)
    # Parses fine but carries no location reference.
    resp = client.post(
        "/api/v1/channels/google/pubsub",
        content=_envelope({"notificationType": "NEW_PHOTO"}),
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ignored"}
    assert called == []


def test_endpoint_triggers_pull_for_known_location(client, _push_env, monkeypatch):
    recorded: list[list[str]] = []

    async def _record(db_arg, location_ids):
        recorded.append(location_ids)
        return len(location_ids)

    monkeypatch.setattr(google_push, "trigger_pulls_for_locations", _record)
    resp = client.post(
        "/api/v1/channels/google/pubsub",
        content=_envelope(
            {"notificationType": "NEW_REVIEW", "location": "accounts/a/locations/l9"}
        ),
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "triggered": 1}
    assert recorded == [["l9"]]


def test_endpoint_acks_malformed_push_as_ignored(client, _push_env):
    # Not a Pub/Sub envelope at all: ack, never 5xx (Pub/Sub would retry
    # byte-identical garbage forever; the poll layer is the safety net).
    resp = client.post("/api/v1/channels/google/pubsub", content=b"garbage-bytes")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ignored"}
