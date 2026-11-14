"""Google Business Profile verification: client + live status snapshot.

The Verifications API is the source of truth. These tests pin the request
shapes (so a method/phone/email is never silently dropped) and the status
mapping (Voice of Merchant, pending request, completed request) without
network calls.
"""
import pytest

from app.modules.channels import router as channels_router
from app.modules.channels.google_reviews import GoogleReviewsClient
from app.modules.channels.models import VerificationRecord
from app.modules.users.models import User


class _FakeClient:
    def __init__(self, *, state=None, options=None, verifications=None):
        self.state = state or {}
        self.options = options or []
        self.verifications = verifications or []
        self.verify_calls: list[dict] = []
        self.complete_calls: list[tuple[str, str]] = []
        self.closed = False

    async def get_voice_of_merchant_state(self, location_id):
        return self.state

    async def fetch_verification_options(self, location_id, language_code="en"):
        return self.options

    async def list_verifications(self, location_id):
        return self.verifications

    async def verify_location(self, location_id, **kwargs):
        self.verify_calls.append({"location_id": location_id, **kwargs})
        verification = {
            "name": f"locations/{location_id}/verifications/new",
            "method": kwargs["method"],
            "state": "PENDING",
            "createTime": "2026-11-04T10:00:00Z",
        }
        self.verifications = [*self.verifications, verification]
        return verification

    async def complete_verification(self, name, pin):
        self.complete_calls.append((name, pin))
        verification = {
            "name": name,
            "method": "SMS",
            "state": "COMPLETED",
            "createTime": "2026-11-04T10:00:00Z",
        }
        self.verifications = [
            verification if item.get("name") == name else item
            for item in self.verifications
        ]
        self.state = {"hasVoiceOfMerchant": True}
        return verification

    async def close(self):
        self.closed = True


class _Ctx:
    def __init__(self, user):
        self.user = user

    def channel_level(self, channel_id):
        return "full"

    def can_edit_channel(self, channel_id):
        return True


async def _user(db, user_id) -> User:
    user = User(
        id=user_id,
        email=f"{user_id}@example.com",
        first_name="Test",
        last_name="User",
        password_hash="x",
    )
    db.add(user)
    await db.commit()
    return user


@pytest.mark.asyncio
async def test_client_fetch_options_posts_language_and_returns_methods(monkeypatch):
    client = GoogleReviewsClient("token")
    captured: dict = {}

    async def _fake(method, url, **kwargs):
        captured.update(method=method, url=url, kwargs=kwargs)

        class _Resp:
            status_code = 200

            def json(self):
                return {"options": [{"verificationMethod": "SMS", "phoneNumber": "+9665"}]}

        return _Resp()

    monkeypatch.setattr(client, "_authed_request", _fake)
    options = await client.fetch_verification_options("841", "ar")
    assert options == [{"verificationMethod": "SMS", "phoneNumber": "+9665"}]
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/locations/841:fetchVerificationOptions")
    assert captured["kwargs"]["json"] == {"languageCode": "ar"}
    await client.close()


@pytest.mark.asyncio
async def test_client_verify_maps_sms_fields():
    client = GoogleReviewsClient("token")
    captured: dict = {}

    async def _fake(method, url, **kwargs):
        captured.update(method=method, url=url, kwargs=kwargs)

        class _Resp:
            status_code = 200

            def json(self):
                return {"verification": {"name": "locations/841/verifications/v1"}}

        return _Resp()

    client._authed_request = _fake
    result = await client.verify_location(
        "841", method="SMS", phone_number="+966500000000", language_code="en"
    )
    assert result["name"] == "locations/841/verifications/v1"
    assert captured["url"].endswith("/locations/841:verify")
    assert captured["kwargs"]["json"] == {
        "method": "SMS",
        "languageCode": "en",
        "phoneNumber": "+966500000000",
    }
    await client.close()


@pytest.mark.asyncio
async def test_client_complete_uses_resource_name_and_pin():
    client = GoogleReviewsClient("token")
    captured: dict = {}

    async def _fake(method, url, **kwargs):
        captured.update(method=method, url=url, kwargs=kwargs)

        class _Resp:
            status_code = 200

            def json(self):
                return {"verification": {"state": "COMPLETED"}}

        return _Resp()

    client._authed_request = _fake
    result = await client.complete_verification(
        "locations/841/verifications/v1", "123456"
    )
    assert result["state"] == "COMPLETED"
    assert captured["url"].endswith(
        "/locations/841/verifications/v1:complete"
    )
    assert captured["kwargs"]["json"] == {"pin": "123456"}
    await client.close()


@pytest.mark.asyncio
async def test_live_read_marks_verified_and_saves_the_record(
    db, user_id, channel_id, monkeypatch
):
    user = await _user(db, user_id)
    fake = _FakeClient(
        state={"hasVoiceOfMerchant": True, "hasBusinessAuthority": True},
        verifications=[
            {
                "name": "locations/841/verifications/done",
                "method": "SMS",
                "state": "COMPLETED",
                "createTime": "2026-11-04T10:00:00Z",
            }
        ],
    )

    async def _fake_client(channel, db_):
        return fake, "841"

    monkeypatch.setattr(channels_router, "_verification_client", _fake_client)
    out = await channels_router.get_verification(
        channel_id, language="en", ctx=_Ctx(user), db=db
    )
    assert out.status == "verified"
    assert out.has_voice_of_merchant is True
    assert out.method == "SMS"
    assert out.verified_at is not None
    row = (
        await db.execute(
            VerificationRecord.__table__.select().where(
                VerificationRecord.channel_id == channel_id
            )
        )
    ).mappings().first()
    assert row["status"] == "verified"
    assert fake.closed is True


@pytest.mark.asyncio
async def test_request_verification_calls_google_and_stores_pending_name(
    db, user_id, channel_id, monkeypatch
):
    user = await _user(db, user_id)
    # The verification plan feature must be on for the router gate to let
    # the request through; enable it on the seeded free-trial plan.
    from sqlalchemy import select as _sel

    from app.modules.billing.models import Plan as _Plan

    _plan = (await db.execute(_sel(_Plan).where(_Plan.slug == "free-trial"))).scalar_one()
    _plan.features = {**( _plan.features or {}), "verifications": True}
    await db.commit()
    fake = _FakeClient(
        state={"hasVoiceOfMerchant": False, "verify": {"hasPendingVerification": True}},
        options=[{"verificationMethod": "SMS", "phoneNumber": "+966500000000"}],
    )

    async def _fake_client(channel, db_):
        return fake, "841"

    monkeypatch.setattr(channels_router, "_verification_client", _fake_client)
    body = channels_router.VerificationRequest(
        method="SMS", phone_number="+966500000000"
    )
    out = await channels_router.request_verification(
        channel_id, body=body, ctx=_Ctx(user), db=db
    )
    assert fake.verify_calls[0]["method"] == "SMS"
    assert fake.verify_calls[0]["phone_number"] == "+966500000000"
    assert out.status == "pending"
    assert out.provider_name == "locations/841/verifications/new"

    complete = channels_router.VerificationCompleteRequest(pin="123456")
    await channels_router.complete_verification(
        channel_id, body=complete, ctx=_Ctx(user), db=db
    )
    assert fake.complete_calls == [("locations/841/verifications/new", "123456")]


@pytest.mark.asyncio
async def test_empty_placeholder_option_is_filtered_and_explained(
    db, user_id, channel_id, monkeypatch
):
    """Google returns `[{}]` when the caller has no business authority."""
    user = await _user(db, user_id)
    fake = _FakeClient(
        state={
            "hasVoiceOfMerchant": False,
            "hasBusinessAuthority": False,
            "verify": {"hasPendingVerification": False},
        },
        options=[{}],
        verifications=[{
            "name": "locations/841/verifications/failed",
            "method": "SMS",
            "state": "FAILED",
            "createTime": "2026-09-16T10:08:21Z",
        }],
    )

    async def _fake_client(channel, db_):
        return fake, "841"

    monkeypatch.setattr(channels_router, "_verification_client", _fake_client)
    out = await channels_router.get_verification(
        channel_id, language="en", ctx=_Ctx(user), db=db
    )
    assert out.options == []
    assert out.status == "failed"
    assert "business authority" in (out.provider_error or "")


@pytest.mark.asyncio
async def test_status_mapping_covers_required_and_failed():
    assert channels_router._verification_status(
        {"hasVoiceOfMerchant": False, "verify": {}}, []
    )[0] == "required"
    assert channels_router._verification_status(
        {"hasVoiceOfMerchant": False},
        [{"state": "FAILED", "createTime": "2026-11-04T10:00:00Z"}],
    )[0] == "failed"
    assert channels_router._verification_status(
        {"hasVoiceOfMerchant": False, "complyWithGuidelines": {}}, []
    )[0] == "guidelines"
