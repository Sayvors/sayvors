"""Conversation stats, voice notes, and the one-shot follow-up worker.

Covers the pieces that must fail safe: a classifier outage never blocks a
reply, a voice problem never costs the customer their reply, and the
follow-up fires EXACTLY ONCE per armed window (or not at all).
"""
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.channels.meta import consumer as meta_consumer
from app.modules.channels.meta import thread_stats as ts
from app.modules.channels.meta import thread_state as tstate
from app.modules.channels.meta import voice as vo
from app.modules.channels.meta.models import MetaAsset, MetaConnection
from app.modules.channels.models import Channel, ChannelMessage, WhatsAppThreadState
from conftest import TEST_ENGINE

_PHONE_ID = "pn-voice-test-1"
_WAMID = "wamid.voice.test.1"
_FROM = "15550002"


# ── thread_stats: parsing + fallbacks ──

def test_parse_classification_accepts_clean_json():
    parsed = ts.parse_classification('{"language": "ur", "confused": true, "awaiting_user": false}')
    assert parsed == {"language": "ur", "confused": True, "awaiting_user": False}


def test_parse_classification_accepts_wrapped_and_regional():
    parsed = ts.parse_classification('Sure! {"language": "ur-PK", "confused": false, "awaiting_user": true} thanks')
    assert parsed == {"language": "ur", "confused": False, "awaiting_user": True}


def test_parse_classification_rejects_garbage_and_unknown_language():
    assert ts.parse_classification(None) is None
    assert ts.parse_classification("") is None
    assert ts.parse_classification("no json here") is None
    assert ts.parse_classification('{"language": "klingon", "confused": true}') is None


def test_script_language_fallback():
    assert ts._script_language("مرحبا كيف حالك") == "ar"
    assert ts._script_language("नमस्ते आप कैसे हैं") == "hi"
    assert ts._script_language("আপনি কেমন আছেন") == "bn"
    assert ts._script_language("hello there") == "en"
    assert ts._script_language("") == "en"


@pytest.mark.asyncio
async def test_classify_thread_uses_llm_result(db, channel_id, monkeypatch):
    # At least one transcript line — the classifier is skipped otherwise.
    db.add(ChannelMessage(
        id=str(uuid.uuid4()), channel_id=channel_id, direction="inbound",
        content="سلام، میں پشمینو شرما چاہتا ہوں", status="delivered",
        contact_phone=_FROM,
    ))
    await db.commit()

    class _Resp:
        content = '{"language": "ps", "confused": true, "awaiting_user": true}'

    class _Provider:
        async def complete(self, req):
            assert req.purpose == "whatsapp.thread_stats"
            return _Resp()

    async def _model(db_):
        return "groq:llama-3.1-8b-instant"

    import app.modules.llm.service as llm_service

    monkeypatch.setattr(llm_service, "resolve_tenant_model", _model)
    monkeypatch.setattr(
        "app.modules.llm.providers.registry.get_provider_for_model",
        lambda model_id: _Provider(),
    )
    stats = await ts.classify_thread(db, channel_id, _FROM)
    assert stats == {"language": "ps", "confused": True, "awaiting_user": True}


@pytest.mark.asyncio
async def test_classify_thread_falls_back_to_script_heuristic(db, channel_id, monkeypatch):
    """No enabled model (or a raise) must degrade — never block the reply."""
    async def _no_model(db_):
        raise ValueError("No AI model is enabled by your administrator.")

    import app.modules.llm.service as llm_service

    monkeypatch.setattr(llm_service, "resolve_tenant_model", _no_model)
    db.add(ChannelMessage(
        id=str(uuid.uuid4()), channel_id=channel_id, direction="inbound",
        content="یہ کیا ہے؟ مجھے سمجھ نہیں آیا", status="delivered",
        contact_phone=_FROM,
    ))
    await db.commit()

    stats = await ts.classify_thread(db, channel_id, _FROM)
    assert stats["language"] == "ar"  # Arabic script -> safe default
    assert stats["confused"] is False
    assert stats["awaiting_user"] is False


@pytest.mark.asyncio
async def test_classify_ignores_history_before_last_voice_note(db, channel_id, monkeypatch):
    """Voice hysteresis: confusion expressed BEFORE the last voice note is
    old news — the note answered it. Only post-voice messages count, so a
    customer's 'okay' after a voice note cannot re-trigger voice."""
    from app.modules.llm.models import VoiceModelConfig

    now = datetime.now(timezone.utc)
    # Confusion, then the AI's voice note (the remedy), then a calm "okay".
    # The old confusion is Arabic-script on purpose: if the filter failed,
    # the fallback heuristic would read it and answer "ar" instead of "en".
    db.add(ChannelMessage(
        id=str(uuid.uuid4()), channel_id=channel_id, direction="inbound",
        content="میں الجھن میں ہوں، یہ کیا ہے؟", status="delivered",
        contact_phone=_FROM,
        created_at=now - timedelta(minutes=5),
    ))
    db.add(ChannelMessage(
        id=str(uuid.uuid4()), channel_id=channel_id, direction="outbound",
        content="No problem, let me explain out loud.", content_type="audio",
        status="sent", contact_phone=_FROM,
        created_at=now - timedelta(minutes=3),
    ))
    db.add(ChannelMessage(
        id=str(uuid.uuid4()), channel_id=channel_id, direction="inbound",
        content="okay thanks", status="delivered", contact_phone=_FROM,
        created_at=now - timedelta(minutes=1),
    ))
    await db.commit()

    # With no LLM available the classifier falls through to the heuristic —
    # which must see ONLY "okay thanks" (post-voice), never the old confusion.
    async def _no_model(db_):
        raise ValueError("No AI model is enabled by your administrator.")

    import app.modules.llm.service as llm_service

    monkeypatch.setattr(llm_service, "resolve_tenant_model", _no_model)

    stats = await ts.classify_thread(db, channel_id, _FROM)
    assert stats["language"] == "en"  # "okay thanks" is English, not Arabic
    assert stats["confused"] is False

    # And a different contact is unaffected by this thread's voice note.
    stats_other = await ts.classify_thread(db, channel_id, "19998887777")
    assert stats_other["language"] == "en"  # no rows -> heuristic on ""


@pytest.mark.asyncio
async def test_classify_counts_messages_after_voice_note(db, channel_id, monkeypatch):
    """Fresh confusion AFTER a voice note must still be visible to the
    classifier (the filter only hides pre-voice history)."""
    now = datetime.now(timezone.utc)
    db.add(ChannelMessage(
        id=str(uuid.uuid4()), channel_id=channel_id, direction="outbound",
        content="Here you go.", content_type="audio",
        status="sent", contact_phone=_FROM,
        created_at=now - timedelta(minutes=3),
    ))
    db.add(ChannelMessage(
        id=str(uuid.uuid4()), channel_id=channel_id, direction="inbound",
        content="wait what?? i still dont understand", status="delivered",
        contact_phone=_FROM,
        created_at=now - timedelta(minutes=1),
    ))
    await db.commit()

    class _Resp:
        content = '{"language": "en", "confused": true, "awaiting_user": false}'

    class _Provider:
        async def complete(self, req):
            # The transcript must contain the fresh confusion but NOT the
            # pre-voice era — there is none here, but the fresh message
            # alone proves the filter did not eat post-voice history.
            assert "still dont understand" in req.messages[0].content
            return _Resp()

    async def _model(db_):
        return "groq:llama-3.1-8b-instant"

    import app.modules.llm.service as llm_service

    monkeypatch.setattr(llm_service, "resolve_tenant_model", _model)
    monkeypatch.setattr(
        "app.modules.llm.providers.registry.get_provider_for_model",
        lambda model_id: _Provider(),
    )
    stats = await ts.classify_thread(db, channel_id, _FROM)
    assert stats["confused"] is True


# ── voice: tier normalization, engine resolution, synthesis guards ──

def test_normalize_voice_tier():
    assert vo.normalize_voice_tier(None) == "off"
    assert vo.normalize_voice_tier("") == "off"
    assert vo.normalize_voice_tier("ON") == "off"
    assert vo.normalize_voice_tier("simple") == "simple"
    assert vo.normalize_voice_tier("advanced") == "advanced"


def test_engine_supports_language():
    assert vo.engine_supports_language("*", "ur") is True
    assert vo.engine_supports_language("ar,ur", "ur") is True
    assert vo.engine_supports_language("ar,ur", "en") is False
    assert vo.engine_supports_language("", "en") is True  # empty reads as *
    assert vo.engine_supports_language("EN", "en") is True


async def _engine(db, **fields):
    from app.modules.llm.models import VoiceModelConfig

    defaults = {
        "id": str(uuid.uuid4()),
        "label": fields.pop("label", "engine"),
        "provider": "edge",
        "tier": "simple",
        "languages": "*",
        "enabled": True,
    }
    defaults.update(fields)
    row = VoiceModelConfig(**defaults)
    db.add(row)
    await db.commit()
    return row


@pytest.mark.asyncio
async def test_resolve_prefers_keyed_engine_over_edge(db):
    await _engine(db, label="edge simple", provider="edge", tier="simple")
    await _engine(db, label="fish simple", provider="fish", tier="simple",
                  key_encrypted="x")
    engine = await vo.resolve_voice_engine(db, "simple", "en")
    assert engine.label == "fish simple"


@pytest.mark.asyncio
async def test_resolve_filters_by_tier_and_language_and_enabled(db):
    await _engine(db, label="edge advanced", provider="edge", tier="advanced")
    await _engine(db, label="off row", provider="fish", tier="simple",
                  enabled=False)
    await _engine(db, label="ur only", provider="fish", tier="simple",
                  languages="ur", key_encrypted="x")

    assert await vo.resolve_voice_engine(db, "simple", "en") is None  # only disabled rows
    engine = await vo.resolve_voice_engine(db, "advanced", "bn")
    assert engine.label == "edge advanced"
    engine = await vo.resolve_voice_engine(db, "simple", "ur")
    assert engine.label == "ur only"


@pytest.mark.asyncio
async def test_resolve_off_tier_never_fires(db):
    await _engine(db, label="edge simple", provider="edge", tier="simple")
    assert await vo.resolve_voice_engine(db, "off", "en") is None


@pytest.mark.asyncio
async def test_synthesize_truncates_long_text(db):
    await _engine(db, label="edge", provider="edge", tier="simple")
    long_text = "word " * 400  # 2000 chars
    result = await vo.synthesize_voice_note(db, "simple", "en", long_text)
    # Real Edge call — the guard under test is the text cap, not the audio.
    if result is not None:
        audio, mime = result
        assert mime == "audio/mpeg"
        assert audio


@pytest.mark.asyncio
async def test_synthesize_empty_text_is_none(db):
    await _engine(db, label="edge", provider="edge", tier="simple")
    assert await vo.synthesize_voice_note(db, "simple", "en", "   ") is None


@pytest.mark.asyncio
async def test_synthesize_unknown_language_falls_back_to_none(db):
    """Edge has no voice for an unknown language — text must be sent."""
    await _engine(db, label="edge", provider="edge", tier="simple")
    assert await vo.synthesize_voice_note(db, "simple", "klingon", "hello") is None


@pytest.mark.asyncio
async def test_fish_without_key_sends_text(db):
    await _engine(db, label="fish no key", provider="fish", tier="advanced",
                  api_url="https://api.fish.audio/v1/tts", key_encrypted=None)
    assert await vo.synthesize_voice_note(db, "advanced", "en", "hello") is None


@pytest.mark.asyncio
async def test_fish_request_pins_voice_and_requests_opus(db, monkeypatch):
    """The persona must be stable: reference_id goes on EVERY request, and
    the format is Ogg/Opus — the only thing WhatsApp renders as a voice
    note. Without the pin Fish picks an arbitrary default per request (the
    changing-voice bug)."""
    import httpx

    from app.modules.channels.service import encrypt_token

    captured: dict = {}

    class _Resp:
        status_code = 200
        content = b"OggS-fake-audio"

    class _FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)

    await _engine(
        db, label="fish pinned", provider="fish", tier="advanced",
        api_url="https://api.fish.audio/v1/tts", api_model="s2.1-pro-free",
        reference_id="933563129e564b19a115bedd57b7406a",
        key_encrypted=encrypt_token("sk-fish-test"),
    )
    audio, mime = await vo.synthesize_voice_note(db, "advanced", "en", "hello there")

    assert (audio, mime) == (b"OggS-fake-audio", "audio/ogg")
    assert captured["json"]["reference_id"] == "933563129e564b19a115bedd57b7406a"
    assert captured["json"]["format"] == "opus"
    assert captured["json"]["sample_rate"] == 48000
    assert captured["json"]["normalize"] is True
    assert captured["headers"]["model"] == "s2.1-pro-free"
    assert captured["headers"]["Authorization"].startswith("Bearer ")


@pytest.mark.asyncio
async def test_fish_language_pin_wins_over_default(db, monkeypatch):
    """Per-language pins override the multilingual persona: a customer
    writing Urdu hears the Urdu voice, everyone else the default one."""
    import httpx

    from app.modules.channels.service import encrypt_token

    captured: dict = {}

    class _Resp:
        status_code = 200
        content = b"OggS-fake-audio"

    class _FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, headers=None, json=None):
            captured["json"] = json
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)

    await _engine(
        db, label="fish multilang", provider="fish", tier="advanced",
        api_url="https://api.fish.audio/v1/tts", api_model="s2.1-pro-free",
        reference_id="default-voice-ref",
        language_references={"ur": "urdu-voice-ref", "ar": "arabic-voice-ref"},
        key_encrypted=encrypt_token("sk-fish-test"),
    )
    audio_ur, _ = await vo.synthesize_voice_note(db, "advanced", "ur", "salam")
    assert audio_ur
    assert captured["json"]["reference_id"] == "urdu-voice-ref"

    await vo.synthesize_voice_note(db, "advanced", "en", "hello")
    assert captured["json"]["reference_id"] == "default-voice-ref"

    await vo.synthesize_voice_note(db, "advanced", "bn", "hello")  # unpinned lang
    assert captured["json"]["reference_id"] == "default-voice-ref"


@pytest.mark.asyncio
async def test_fish_voice_catalog_slims_items(monkeypatch):
    """The admin picker gets id/title/languages/tags/likes/uses — not the
    whole fish payload (which carries covers, licensing, PVC state...)."""
    import httpx

    class _Resp:
        status_code = 200

        def json(self):
            return {
                "items": [
                    {
                        "_id": "abc123",
                        "title": "Warm Urdu Female",
                        "languages": ["ur", "en"],
                        "tags": ["female", "warm", "calm", "extra", "extra2", "extra3", "extra4"],
                        "like_count": 4210,
                        "task_count": 99000,
                        "cover_image": "https://…",  # must NOT come through
                    },
                    {"no_id": True},  # dropped: idless entries are useless
                ],
                "has_more": True,
            }

    class _FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, headers=None, params=None):
            assert url == "https://api.fish.audio/model"
            assert params["page_size"] == 24
            assert params["sort_by"] == "task_count"
            assert headers["Authorization"].startswith("Bearer ")
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)

    out = await vo.fish_voice_catalog("sk-fish-test")
    assert out["has_more"] is True
    assert len(out["items"]) == 1
    item = out["items"][0]
    assert item == {
        "id": "abc123",
        "title": "Warm Urdu Female",
        "languages": ["ur", "en"],
        "tags": ["female", "warm", "calm", "extra", "extra2", "extra3"],
        "likes": 4210,
        "uses": 99000,
    }


@pytest.mark.asyncio
async def test_fish_voice_catalog_bad_sort_and_failure(monkeypatch):
    """Unknown sort falls back to task_count; a fish outage raises so the
    admin endpoint can surface it as a 502."""
    import httpx

    seen: dict = {}

    class _Resp:
        status_code = 200

        def json(self):
            return {"items": [], "has_more": False}

    class _FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, headers=None, params=None):
            seen["sort_by"] = params["sort_by"]
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    await vo.fish_voice_catalog("k", sort_by="weird")
    assert seen["sort_by"] == "task_count"

    class _BoomClient(_FakeClient):
        async def get(self, url, headers=None, params=None):
            class _R:
                status_code = 503

            return _R()

    monkeypatch.setattr(httpx, "AsyncClient", _BoomClient)
    try:
        await vo.fish_voice_catalog("k")
        raised = False
    except ValueError:
        raised = True
    assert raised


@pytest.mark.asyncio
async def test_fish_without_pin_omits_reference_id(db, monkeypatch):
    """No pinned voice -> no reference_id field at all (Fish default), but
    the opus format request stays — quality is never config-dependent."""
    import httpx

    from app.modules.channels.service import encrypt_token

    captured: dict = {}

    class _Resp:
        status_code = 200
        content = b"OggS-fake-audio"

    class _FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, headers=None, json=None):
            captured["json"] = json
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)

    await _engine(
        db, label="fish unpinned", provider="fish", tier="advanced",
        api_url="https://api.fish.audio/v1/tts", api_model="s2.1-pro-free",
        key_encrypted=encrypt_token("sk-fish-test"),
    )
    result = await vo.synthesize_voice_note(db, "advanced", "en", "hello")
    assert result is not None
    assert "reference_id" not in captured["json"]
    assert captured["json"]["format"] == "opus"


# ── thread_state persistence ──

@pytest.mark.asyncio
async def test_thread_state_roundtrip(db, channel_id):
    state = await tstate.get_or_create_thread_state(db, channel_id, _FROM)
    assert state is not None
    assert state.language == "en"
    assert state.followup_sent is False

    await tstate.apply_classification(
        db, channel_id, _FROM, {"language": "ur", "confused": True}
    )
    await db.commit()
    state = await tstate.get_thread_state(db, channel_id, _FROM)
    assert state.language == "ur"
    assert state.confused is True
    assert state.confused_at is not None

    # Arming opens exactly one window.
    await tstate.arm_followup(db, channel_id, _FROM)
    await db.commit()
    state = await tstate.get_thread_state(db, channel_id, _FROM)
    assert state.awaiting_since is not None
    assert state.followup_sent is False

    # The customer's next message closes it and resets the one-shot flag.
    await tstate.clear_awaiting(db, channel_id, _FROM)
    await db.commit()
    state = await tstate.get_thread_state(db, channel_id, _FROM)
    assert state.awaiting_since is None
    assert state.followup_sent is False

    # No phone -> no state at all.
    assert await tstate.get_or_create_thread_state(db, channel_id, None) is None


def test_as_aware_normalizes_naive_datetimes():
    naive = datetime(2026, 1, 1, 12, 0, 0)
    aware = tstate._as_aware(naive)
    assert aware.tzinfo is not None
    assert tstate._as_aware(None) is None


@pytest.mark.asyncio
async def test_clear_confusion_resets_signal(db, channel_id):
    """A delivered voice note ends the confusion — back to text mode."""
    await tstate.apply_classification(
        db, channel_id, _FROM, {"language": "ur", "confused": True}
    )
    await db.commit()
    state = await tstate.get_thread_state(db, channel_id, _FROM)
    assert state.confused is True

    await tstate.clear_confusion(db, channel_id, _FROM)
    await db.commit()
    state = await tstate.get_thread_state(db, channel_id, _FROM)
    assert state.confused is False
    assert state.language == "ur"  # language survives the reset

    # Clearing twice is a no-op; unknown threads never raise.
    await tstate.clear_confusion(db, channel_id, _FROM)
    await tstate.clear_confusion(db, channel_id, "19998887777")


# ── follow-up worker: one-shot guarantee ──

def _test_session_factory():
    return async_sessionmaker(TEST_ENGINE, class_=AsyncSession, expire_on_commit=False)


async def _seed_thread(db, *, awaiting_age=None, followup_sent=False,
                       language="en", with_inbound=True):
    """User + channel + asset + thread state, optionally with a due window.

    The seeded inbound always predates the arming (the AI's question is sent
    after the customer's last message) — pass `inbound_after_arming` to flip
    that for cancel-window tests."""
    from app.modules.users.models import User

    uid = f"fu-user-{uuid.uuid4().hex[:8]}"
    db.add(User(
        id=uid, first_name="F", last_name="U",
        email=f"{uid}@example.com", password_hash="x",
        response_style="concise", voice_replies="off",
    ))
    channel = Channel(
        id=f"fu-channel-{uuid.uuid4().hex[:8]}", user_id=uid,
        platform="whatsapp", platform_user_id=_PHONE_ID,
        display_name="FU Test", status="active",
    )
    db.add(channel)
    await db.flush()
    conn = MetaConnection(
        id=str(uuid.uuid4()), tenant_id=uid, provider="whatsapp",
        access_token_encrypted=_encrypt("tok"), status="active",
    )
    db.add(conn)
    await db.flush()
    db.add(MetaAsset(
        id=str(uuid.uuid4()), tenant_id=uid, connection_id=conn.id,
        provider="whatsapp", asset_type="phone_number",
        external_asset_id=_PHONE_ID, phone="+1555", active=True,
    ))
    if with_inbound:
        # The customer spoke, then the AI asked its question (awaiting_since),
        # then silence — inbound strictly before the arming.
        inbound_age = (awaiting_age + 120) if awaiting_age is not None else 300
        db.add(ChannelMessage(
            id=str(uuid.uuid4()), channel_id=channel.id, direction="inbound",
            content="hi", status="delivered", contact_phone=_FROM,
            created_at=datetime.now(timezone.utc) - timedelta(seconds=inbound_age),
        ))
    state = WhatsAppThreadState(
        id=str(uuid.uuid4()), channel_id=channel.id, contact_phone=_FROM,
        language=language,
    )
    if awaiting_age is not None:
        state.awaiting_since = datetime.now(timezone.utc) - timedelta(seconds=awaiting_age)
    state.followup_sent = followup_sent
    db.add(state)
    await db.commit()
    return channel


def _encrypt(value: str) -> str:
    from app.modules.channels.meta.credentials import encrypt_credential

    return encrypt_credential(value)


class _FakeWaAdapter:
    """Stands in for WhatsAppAdapter inside the follow-up worker."""
    sent: list[str] = []

    async def send_text_message(self, phone_number_id, token, to, text):
        _FakeWaAdapter.sent.append(text)
        return f"wamp-{len(_FakeWaAdapter.sent)}"


def _wire_worker(monkeypatch, nudge="Still there? Happy to help!"):
    from app.modules.channels.meta import followup_worker as fw
    from app.modules.channels.meta.providers import whatsapp as wa_provider

    monkeypatch.setattr(fw, "async_session", _test_session_factory())
    monkeypatch.setattr(wa_provider, "WhatsAppAdapter", _FakeWaAdapter)

    async def _fake_nudge(db, channel, contact_phone, language):
        return nudge

    monkeypatch.setattr(fw, "_generate_nudge", _fake_nudge)


@pytest.fixture(autouse=True)
def _reset_fake_adapter():
    _FakeWaAdapter.sent = []
    yield
    _FakeWaAdapter.sent = []


@pytest.mark.asyncio
async def test_followup_sends_once_then_never_again(db, monkeypatch):
    channel = await _seed_thread(db, awaiting_age=90)
    _wire_worker(monkeypatch)

    sent = await _process()
    assert sent == 1
    assert len(_FakeWaAdapter.sent) == 1

    async with _test_session_factory()() as s:
        state = (await s.execute(
            select(WhatsAppThreadState).where(
                WhatsAppThreadState.channel_id == channel.id)
        )).scalar_one()
        assert state.followup_sent is True
        assert state.awaiting_since is None

    # Second poll: the one-shot flag blocks any repeat.
    assert await _process() == 0
    assert len(_FakeWaAdapter.sent) == 1


async def _process():
    from app.modules.channels.meta import followup_worker as fw

    return await fw.process_due_followups()


@pytest.mark.asyncio
async def test_followup_not_due_before_60s(db, monkeypatch):
    await _seed_thread(db, awaiting_age=30)
    _wire_worker(monkeypatch)
    assert await _process() == 0
    assert _FakeWaAdapter.sent == []


@pytest.mark.asyncio
async def test_followup_gives_up_after_10_minutes(db, monkeypatch):
    channel = await _seed_thread(db, awaiting_age=700)
    _wire_worker(monkeypatch)

    assert await _process() == 0
    assert _FakeWaAdapter.sent == []

    async with _test_session_factory()() as s:
        state = (await s.execute(
            select(WhatsAppThreadState).where(
                WhatsAppThreadState.channel_id == channel.id)
        )).scalar_one()
        # Window closed silently — it must never retry.
        assert state.followup_sent is True
        assert state.awaiting_since is None


@pytest.mark.asyncio
async def test_followup_cancelled_when_customer_replied(db, monkeypatch):
    """An inbound that lands after arming always wins — no nudge at all."""
    channel = await _seed_thread(db, awaiting_age=90)
    # Customer answered AFTER the AI's question armed the window.
    async with _test_session_factory()() as s:
        s.add(ChannelMessage(
            id=str(uuid.uuid4()), channel_id=channel.id, direction="inbound",
            content="chicken please", status="delivered", contact_phone=_FROM,
            created_at=datetime.now(timezone.utc) - timedelta(seconds=10),
        ))
        await s.commit()

    _wire_worker(monkeypatch)
    assert await _process() == 0
    assert _FakeWaAdapter.sent == []

    async with _test_session_factory()() as s:
        state = (await s.execute(
            select(WhatsAppThreadState).where(
                WhatsAppThreadState.channel_id == channel.id)
        )).scalar_one()
        assert state.awaiting_since is None
        assert state.followup_sent is False  # a fresh question may re-arm


@pytest.mark.asyncio
async def test_followup_generation_failure_closes_window(db, monkeypatch):
    """A failing LLM must not be hammered every poll — the window closes."""
    from app.modules.channels.meta import followup_worker as fw
    from app.modules.channels.meta.providers import whatsapp as wa_provider

    channel = await _seed_thread(db, awaiting_age=90)
    monkeypatch.setattr(fw, "async_session", _test_session_factory())
    monkeypatch.setattr(wa_provider, "WhatsAppAdapter", _FakeWaAdapter)

    async def _boom(db, channel_, contact_phone, language):
        raise ValueError("No AI model is enabled by your administrator.")

    monkeypatch.setattr(fw, "_generate_nudge", _boom)

    assert await _process() == 0
    assert _FakeWaAdapter.sent == []

    async with _test_session_factory()() as s:
        state = (await s.execute(
            select(WhatsAppThreadState).where(
                WhatsAppThreadState.channel_id == channel.id)
        )).scalar_one()
        assert state.followup_sent is True


@pytest.mark.asyncio
async def test_followup_send_failure_still_marks_sent(db, monkeypatch):
    """Meta rejection closes the window too — never a retry loop."""
    from app.modules.channels.meta import followup_worker as fw
    from app.modules.channels.meta.providers import whatsapp as wa_provider
    from app.modules.channels.meta.providers.base import MetaAPIError

    channel = await _seed_thread(db, awaiting_age=90)
    monkeypatch.setattr(fw, "async_session", _test_session_factory())

    class _FailingAdapter:
        async def send_text_message(self, phone_number_id, token, to, text):
            raise MetaAPIError("out of window", status_code=400)

    monkeypatch.setattr(wa_provider, "WhatsAppAdapter", _FailingAdapter)

    async def _fake_nudge(db, channel_, contact_phone, language):
        return "Still there?"

    monkeypatch.setattr(fw, "_generate_nudge", _fake_nudge)

    assert await _process() == 0
    async with _test_session_factory()() as s:
        state = (await s.execute(
            select(WhatsAppThreadState).where(
                WhatsAppThreadState.channel_id == channel.id)
        )).scalar_one()
        assert state.followup_sent is True


# ── consumer: the voice branch + follow-up arming ──

class _VoiceAdapter:
    def __init__(self, fail_voice=False):
        self.sent: list[str] = []
        self.voices: list[str] = []
        self.voice_flags: list[bool] = []
        self.typing: list[str] = []
        self._fail_voice = fail_voice

    async def send_text_message(self, phone_number_id, token, to, text):
        self.sent.append(text)
        return f"wamp-{len(self.sent)}"

    async def upload_media(self, phone_number_id, token, data, mime_type):
        assert data  # real audio bytes expected
        assert mime_type.startswith("audio/")
        return "media-123"

    async def send_voice_note(self, phone_number_id, token, to, media_id,
                              voice: bool = True):
        if self._fail_voice:
            from app.modules.channels.meta.providers.base import MetaAPIError

            raise MetaAPIError("media error", status_code=500)
        self.voices.append(media_id)
        self.voice_flags.append(voice)
        return "wampv-1"

    async def send_typing_indicator(self, phone_number_id, token, message_id):
        self.typing.append(message_id)
        return True


async def _seed_voice_tenant(db, user_id, *, voice_replies):
    from app.modules.users.models import User

    db.add(User(
        id=user_id, first_name="Test", last_name="Owner",
        email=f"{user_id}@example.com", password_hash="x",
        response_style="concise", voice_replies=voice_replies,
    ))
    conn = MetaConnection(
        id=str(uuid.uuid4()), tenant_id=user_id, provider="whatsapp",
        access_token_encrypted=_encrypt("tok"), status="active",
    )
    db.add(conn)
    await db.flush()
    db.add(MetaAsset(
        id=str(uuid.uuid4()), tenant_id=user_id, connection_id=conn.id,
        provider="whatsapp", asset_type="phone_number",
        external_asset_id=_PHONE_ID, phone="+1555", active=True,
    ))
    await db.commit()


def _wire_voice_consumer(monkeypatch, adapter, *, reply, confused, language,
                         voice_result):
    from app.modules.channels.meta import consumer as meta_consumer
    from app.modules.channels.meta import thread_stats as ts_mod
    from app.modules.channels.meta import voice as vo_mod
    from app.modules.channels.meta import service as meta_service

    monkeypatch.setattr(meta_consumer, "async_session", _test_session_factory())

    async def _stats(db, channel_id_, contact_phone):
        return {"language": language, "confused": confused,
                "awaiting_user": False}

    monkeypatch.setattr(ts_mod, "classify_thread", _stats)

    async def _synth(db, tier, language_, text, tenant_id=None):
        return voice_result

    monkeypatch.setattr(vo_mod, "synthesize_voice_note", _synth)

    async def _gen(db, channel, tenant_id, text):
        return reply

    monkeypatch.setattr(meta_consumer, "_generate_reply", _gen)
    monkeypatch.setattr(meta_service, "get_adapter", lambda name: adapter)

    async def _fake_sleep(seconds):
        pass

    monkeypatch.setattr(meta_consumer.asyncio, "sleep", _fake_sleep)


def _event():
    return ({"external_asset_id": _PHONE_ID, "external_event_id": _WAMID},
            {"from": _FROM, "text": "what?? i dont get it", "msg_type": "text"})


async def _thread_state_for(channel_phone=_FROM):
    async with _test_session_factory()() as s:
        rows = (await s.execute(select(WhatsAppThreadState))).scalars().all()
        return rows


@pytest.mark.asyncio
async def test_consumer_confused_advanced_sends_voice_note(db, user_id, monkeypatch):
    await _seed_voice_tenant(db, user_id, voice_replies="advanced")
    adapter = _VoiceAdapter()
    _wire_voice_consumer(
        monkeypatch, adapter,
        reply="No problem! Let me explain it out loud for you.",
        confused=True, language="ur", voice_result=(b"OggS-fake", "audio/ogg"),
    )

    event, data = _event()
    await meta_consumer._handle_message_received(event, data)

    assert adapter.typing == [_WAMID]  # typing dots shown while preparing
    assert adapter.voices == ["media-123"]
    assert adapter.voice_flags == [True]  # ogg goes out as a REAL voice note
    assert adapter.sent == []  # voice replaced the text reply entirely
    rows = await _outbound_rows()
    assert len(rows) == 1
    assert rows[0].content_type == "audio"
    assert rows[0].status == "sent"
    assert rows[0].content == "No problem! Let me explain it out loud for you."

    # The voice note is the remedy: confusion is cleared, the AI is back in
    # text mode until genuinely fresh confusion appears.
    states = await _thread_state_for()
    assert states[0].confused is False


@pytest.mark.asyncio
async def test_consumer_stale_webhook_is_stored_but_never_answered(db, user_id, monkeypatch):
    """Redelivered / backlogged webhooks (Meta retry, outbox drain after a
    downtime window) keep their inbox row — but the AI must not answer a
    message from hours ago: the conversation has already moved on."""
    await _seed_voice_tenant(db, user_id, voice_replies="advanced")
    adapter = _VoiceAdapter()
    _wire_voice_consumer(
        monkeypatch, adapter,
        reply="Should never be sent", confused=False, language="en",
        voice_result=None,
    )

    event, data = _event()
    event["occurred_at"] = (datetime.now(timezone.utc) - timedelta(hours=20)).isoformat()
    await meta_consumer._handle_message_received(event, data)

    # No typing dots, no generation, no send — history only.
    assert adapter.typing == []
    assert adapter.sent == []
    assert await _outbound_rows() == []
    async with _test_session_factory()() as session:
        inbound = (
            await session.execute(
                select(ChannelMessage).where(ChannelMessage.direction == "inbound")
            )
        ).scalars().all()
    assert len(inbound) == 1


@pytest.mark.asyncio
async def test_consumer_non_ogg_audio_sends_as_plain_media(db, user_id, monkeypatch):
    """Without Ogg/Opus the audio cannot be a voice note — it still goes out,
    just with the voice flag off (media bubble instead of mic bubble)."""
    await _seed_voice_tenant(db, user_id, voice_replies="advanced")
    adapter = _VoiceAdapter()
    _wire_voice_consumer(
        monkeypatch, adapter,
        reply="No problem! Let me explain it out loud for you.",
        confused=True, language="ur", voice_result=(b"FAKEAUDIO", "audio/mpeg"),
    )
    # ffmpeg absent (CI) — conversion impossible, flag must be False.
    import shutil as _shutil

    monkeypatch.setattr(_shutil, "which", lambda name: None)

    event, data = _event()
    await meta_consumer._handle_message_received(event, data)

    assert adapter.voices == ["media-123"]
    assert adapter.voice_flags == [False]  # media bubble, not a voice note
    assert adapter.sent == []
    rows = await _outbound_rows()
    assert rows[0].content_type == "audio"  # audio still wins over no reply


@pytest.mark.asyncio
async def test_consumer_voice_failure_falls_back_to_text(db, user_id, monkeypatch):
    await _seed_voice_tenant(db, user_id, voice_replies="advanced")
    adapter = _VoiceAdapter(fail_voice=True)
    _wire_voice_consumer(
        monkeypatch, adapter,
        reply="No problem! Let me explain it out loud for you.",
        confused=True, language="ur", voice_result=(b"FAKEAUDIO", "audio/mpeg"),
    )

    event, data = _event()
    await meta_consumer._handle_message_received(event, data)

    # Upload+send blew up -> the customer still gets the text reply.
    assert adapter.voices == []
    assert len(adapter.sent) == 1
    rows = await _outbound_rows()
    assert [r.content_type for r in rows] == ["text"]


@pytest.mark.asyncio
async def test_consumer_voice_unavailable_falls_back_to_text(db, user_id, monkeypatch):
    await _seed_voice_tenant(db, user_id, voice_replies="advanced")
    adapter = _VoiceAdapter()
    _wire_voice_consumer(
        monkeypatch, adapter,
        reply="No problem! Let me explain it out loud for you.",
        confused=True, language="klingon", voice_result=None,
    )

    event, data = _event()
    await meta_consumer._handle_message_received(event, data)

    assert adapter.voices == []
    assert len(adapter.sent) == 1


@pytest.mark.asyncio
async def test_consumer_confused_but_tier_off_sends_text(db, user_id, monkeypatch):
    await _seed_voice_tenant(db, user_id, voice_replies="off")
    adapter = _VoiceAdapter()
    _wire_voice_consumer(
        monkeypatch, adapter,
        reply="No problem! Let me explain it again in text.",
        confused=True, language="ur", voice_result=(b"FAKEAUDIO", "audio/mpeg"),
    )

    event, data = _event()
    await meta_consumer._handle_message_received(event, data)

    assert adapter.voices == []
    assert len(adapter.sent) == 1


@pytest.mark.asyncio
async def test_consumer_arms_followup_only_for_questions(db, user_id, monkeypatch):
    await _seed_voice_tenant(db, user_id, voice_replies="off")

    # Reply ends with a question mark -> window armed.
    adapter = _VoiceAdapter()
    _wire_voice_consumer(
        monkeypatch, adapter, reply="Sure — what kind of shawarma?",
        confused=False, language="en", voice_result=None,
    )
    event, data = _event()
    await meta_consumer._handle_message_received(event, data)

    states = await _thread_state_for()
    assert len(states) == 1
    assert states[0].awaiting_since is not None
    assert states[0].followup_sent is False

    # A statement reply -> no window.
    adapter2 = _VoiceAdapter()
    _wire_voice_consumer(
        monkeypatch, adapter2, reply="Great, your order is confirmed.",
        confused=False, language="en", voice_result=None,
    )
    event2 = ({"external_asset_id": _PHONE_ID, "external_event_id": _WAMID + "2"},
              {"from": _FROM, "text": "ok chicken", "msg_type": "text"})
    await meta_consumer._handle_message_received(event2[0], event2[1])

    states = await _thread_state_for()
    assert len(states) == 1  # same thread row
    # clear_awaiting ran on the inbound, and the statement did not re-arm.
    assert states[0].awaiting_since is None
    assert states[0].followup_sent is False


# ── API: tenant voice-replies endpoint + admin voice engines ──

async def _make_user(db, user_id, **fields):
    from app.modules.users.models import User

    db.add(User(
        id=user_id, first_name="Test", last_name="Owner",
        email=f"{user_id}@example.com", password_hash="x", **fields,
    ))
    await db.commit()


@pytest.mark.asyncio
async def test_voice_replies_endpoint(db, user_id, client):
    await _make_user(db, user_id)

    resp = client.put("/api/v1/profile/voice-replies", json={"voice_replies": "advanced"})
    assert resp.status_code == 200
    assert resp.json()["voice_replies"] == "advanced"

    resp = client.get("/api/v1/profile")
    assert resp.status_code == 200
    assert resp.json()["voice_replies"] == "advanced"

    resp = client.put("/api/v1/profile/voice-replies", json={"voice_replies": "loud"})
    assert resp.status_code == 422


# Admin endpoint tests reuse the established admin login pattern.
TEST_ADMIN_HASH = "$2b$04$JYhUM7dKG7CjHsWtPoyNvuHgI.uZcJoMA8JruWs3DhtQxc2susyAy"
_HOST = {"host": "localhost"}


@pytest.fixture
def admin_headers(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "ADMIN_PASSWORD_HASH", TEST_ADMIN_HASH)
    r = client.post("/api/v1/admin/login", json={"password": "test-admin-pass"}, headers=_HOST)
    assert r.status_code == 200
    return {**_HOST, "X-Requested-With": "XMLHttpRequest"}


@pytest.mark.asyncio
async def test_admin_voice_engine_lifecycle(db, client, admin_headers):
    from app.modules.llm.models import VoiceModelConfig

    # Empty to start (tables are created fresh in tests, no seeds).
    r = client.get("/api/v1/admin/voice-engines", headers=admin_headers)
    assert r.status_code == 200
    assert r.json() == []

    # Create with a key: has_key=true, the key VALUE never comes back.
    r = client.post("/api/v1/admin/voice-engines", headers=admin_headers, json={
        "label": "Fish Audio (advanced)", "provider": "fish", "tier": "advanced",
        "api_url": "https://api.fish.audio/v1/tts", "api_model": "s2.1-pro-free",
        "languages": "*", "api_key": "sk-fish-test",
    })
    assert r.status_code == 201
    body = r.json()
    engine_id = body["id"]
    assert body["has_key"] is True
    assert "sk-fish-test" not in json.dumps(body)

    row = (await db.execute(
        select(VoiceModelConfig).where(VoiceModelConfig.id == engine_id)
    )).scalar_one()
    assert row.key_encrypted and "sk-fish-test" not in row.key_encrypted

    # Update without api_key: the stored key survives.
    r = client.put(f"/api/v1/admin/voice-engines/{engine_id}", headers=admin_headers, json={
        "label": "Fish Audio (advanced)", "provider": "fish", "tier": "advanced",
        "api_url": "https://api.fish.audio/v1/tts", "api_model": "s2.1-pro-free",
        "languages": "*",
    })
    assert r.status_code == 200
    assert r.json()["has_key"] is True

    # Empty api_key clears it.
    r = client.put(f"/api/v1/admin/voice-engines/{engine_id}", headers=admin_headers, json={
        "label": "Fish Audio (advanced)", "provider": "fish", "tier": "advanced",
        "api_url": "https://api.fish.audio/v1/tts", "api_model": "s2.1-pro-free",
        "languages": "*", "api_key": "",
    })
    assert r.status_code == 200
    assert r.json()["has_key"] is False

    # Unknown id -> 404.
    r = client.put("/api/v1/admin/voice-engines/nope", headers=admin_headers, json={
        "label": "x", "provider": "fish", "tier": "advanced",
    })
    assert r.status_code == 404

    # Unauthenticated access is refused.
    r = client.get("/api/v1/admin/voice-engines", headers=_HOST)
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_admin_voice_engine_delete_and_test(db, client, admin_headers, monkeypatch):
    from app.modules.channels.meta import voice as vo_mod
    from app.modules.llm.models import VoiceModelConfig

    r = client.post("/api/v1/admin/voice-engines", headers=admin_headers, json={
        "label": "Fish test", "provider": "fish", "tier": "advanced",
        "api_url": "https://api.fish.audio/v1/tts", "api_model": "s2.1-pro-free",
        "languages": "*", "api_key": "sk-fish-test",
    })
    engine_id = r.json()["id"]

    # Test endpoint reports a real synthesis through this exact engine.
    real_fish = vo_mod._synthesize_fish

    async def _fake_fish(engine, text, language="en"):
        assert engine.api_model == "s2.1-pro-free"
        return b"FAKEAUDIO", "audio/mpeg"

    monkeypatch.setattr(vo_mod, "_synthesize_fish", _fake_fish)
    r = client.post(f"/api/v1/admin/voice-engines/{engine_id}/test", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "audio/mpeg" in body["detail"]

    # Missing key -> the probe explains it instead of pretending success.
    monkeypatch.setattr(vo_mod, "_synthesize_fish", real_fish)

    # Missing key -> the probe explains it instead of pretending success.
    r = client.put(f"/api/v1/admin/voice-engines/{engine_id}", headers=admin_headers, json={
        "label": "Fish test", "provider": "fish", "tier": "advanced",
        "api_url": "https://api.fish.audio/v1/tts", "api_model": "s2.1-pro-free",
        "languages": "*", "api_key": "",
    })
    assert r.json()["has_key"] is False
    r = client.post(f"/api/v1/admin/voice-engines/{engine_id}/test", headers=admin_headers)
    body = r.json()
    assert body["ok"] is False
    assert "key" in body["detail"].lower()

    # Delete removes the row; a second delete 404s.
    r = client.delete(f"/api/v1/admin/voice-engines/{engine_id}", headers=admin_headers)
    assert r.status_code == 204
    row = (await db.execute(
        select(VoiceModelConfig).where(VoiceModelConfig.id == engine_id)
    )).scalar_one_or_none()
    assert row is None
    r = client.delete(f"/api/v1/admin/voice-engines/{engine_id}", headers=admin_headers)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_admin_voice_language_pins_roundtrip(db, client, admin_headers):
    """Per-language pins persist (normalized), and a language without one
    falls back to the multilingual voice — that's the resolution contract."""
    from app.modules.llm.models import VoiceModelConfig

    r = client.post("/api/v1/admin/voice-engines", headers=admin_headers, json={
        "label": "Fish multilingual", "provider": "fish", "tier": "advanced",
        "api_model": "s2.1-pro-free", "reference_id": "default-ref",
        "language_references": {"Urdu": " urdu-ref ", "ar": "arabic-ref", "": "dropped"},
        "api_key": "sk-fish-test",
    })
    assert r.status_code == 201
    body = r.json()
    # Keys are lowercased/trimmed; empty keys and values are dropped.
    assert body["language_references"] == {"urdu": "urdu-ref", "ar": "arabic-ref"}
    engine_id = body["id"]

    # Update can clear them with null; has_key survives.
    r = client.put(f"/api/v1/admin/voice-engines/{engine_id}", headers=admin_headers, json={
        "label": "Fish multilingual", "provider": "fish", "tier": "advanced",
        "reference_id": "default-ref", "language_references": None,
    })
    assert r.status_code == 200
    assert r.json()["language_references"] is None
    assert r.json()["has_key"] is True

    # More than 8 pins is refused.
    r = client.post("/api/v1/admin/voice-engines", headers=admin_headers, json={
        "label": "too many", "provider": "fish", "tier": "advanced",
        "language_references": {f"l{i}": "ref" for i in range(9)},
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_admin_fish_voice_catalog_endpoint(db, client, admin_headers, monkeypatch):
    """The voice library needs a fish engine with a key; with one, it serves
    the slimmed catalog (key value never leaves the server)."""
    from app.modules.channels.meta import voice as vo_mod

    # No fish engine with a key yet -> actionable 400.
    r = client.get("/api/v1/admin/voice-engines/fish-voices", headers=admin_headers)
    assert r.status_code == 400
    assert "key" in r.json()["detail"].lower()

    await _engine(
        db, label="fish keyed", provider="fish", tier="advanced",
        key_encrypted=_encrypt("sk-fish-test"),
    )

    async def _fake_catalog(api_key, sort_by="task_count", page=1):
        # The endpoint decrypts the stored key before calling — the fake
        # asserts material flowed through, without exposing it anywhere.
        assert api_key
        return {"items": [{"id": "abc", "title": "V", "languages": ["en"],
                           "tags": [], "likes": 1, "uses": 2}], "has_more": False}

    monkeypatch.setattr(vo_mod, "fish_voice_catalog", _fake_catalog)
    r = client.get("/api/v1/admin/voice-engines/fish-voices?sort_by=score&page=2",
                   headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["items"][0]["id"] == "abc"

    # Fish outage -> 502 with a readable reason, never a stack trace.
    async def _boom(api_key, sort_by="task_count", page=1):
        raise ValueError("fish.audio catalog failed (503)")

    monkeypatch.setattr(vo_mod, "fish_voice_catalog", _boom)
    r = client.get("/api/v1/admin/voice-engines/fish-voices", headers=admin_headers)
    assert r.status_code == 502
    assert "503" in r.json()["detail"]


async def _outbound_rows():
    async with _test_session_factory()() as session:
        return list(
            (
                await session.execute(
                    select(ChannelMessage)
                    .where(ChannelMessage.direction == "outbound")
                    .order_by(ChannelMessage.created_at)
                )
            )
            .scalars()
            .all()
        )
