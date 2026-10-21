# Text-to-Speech (TTS)

TTS is a platform capability, not a channel feature. Any channel, job or
future call path renders text to audio through one interface; each channel
decides *whether* and *how* to deliver it.

## Layering

```
channels/meta/consumer.py
        │  policy: confusion trigger, 550-char budget, Ogg/Opus, text fallback
        ▼
channels/meta/voice.py              Meta adapter (not a capability)
        │
        ▼
app/modules/tts/api.py              public interface: synthesize / synthesize_stream
        │
        ├── registry.py             tier + language -> VoiceModelConfig
        ├── engines/edge.py         Microsoft Edge neural voices (free)
        ├── engines/fish.py         Fish Audio (keyed, persona pins)
        └── audio.py                ffmpeg container conversion
```

The dependency direction is one-way: `channels → tts`. The TTS module never
imports a channel module, and `tests/test_tts_boundary.py` enforces that.

## Public interface

```python
from app.modules.tts.api import (
    AudioFormat, SynthesisRequest, VoiceRef, synthesize, synthesize_stream,
)

result = await synthesize(SynthesisRequest(
    text="Your order ships tomorrow.",
    language="en",
    tenant_id=tenant_id,
    voice=VoiceRef(tier="advanced"),
    format=AudioFormat.OGG_OPUS,
    purpose="instagram_voice_reply",
))
if result is None:
    send_text()          # voice is not possible — never a reason to drop the reply
else:
    send_audio(result.audio, result.mime_type)
```

* `synthesize` returns `None` for "voice not possible" and **never raises** for
  a rendering problem. Callers must degrade to text.
* `synthesize_stream` yields the same audio in transport-sized chunks. The
  contract is stable so a telephony adapter can consume it today; provider-level
  first-byte streaming can be added inside the engine without touching callers.
* Request and result are plain data — no ORM row and no session crosses the
  boundary. `db` on `synthesize` is a test hook only.

## What stays in the channel

| Concern | Owner | Example |
|---|---|---|
| When to speak | Channel | WhatsApp speaks only when the customer seems confused |
| Text budget | Channel | WhatsApp: 550 chars (~30–40 s) |
| Container | Channel | Meta: Ogg/Opus only; telephony: 8 kHz PCM |
| Attachment + fallback | Channel | Voice note vs media bubble; text on any failure |

Generic TTS keeps only the hard safety ceiling (`MAX_SYNTH_CHARS = 5000`).

## Engine selection

`registry.resolve_engine` honours an explicit `engine_id` (admin probes, tests)
when the row is enabled and covers the language. Otherwise it filters enabled
rows by tier and language and ranks keyed engines before the free Edge
fallback. An admin adding a keyed engine is an explicit upgrade.

Coverage is matched on BCP-47 prefixes: `languages="ar,ur"` serves `ar-EG` only
if the admin lists `ar-eg`; `"*"` serves everything.

## Failure contract

* Provider network/quota/malformed-response errors are caught, logged and
  metered as `failed`; `synthesize` returns `None`.
* Missing API key, unsupported language, no enabled engine → `None` without an
  error log (expected states).
* Conversion failure is not fatal: the native audio is returned with its real
  container so the channel can still send a plain audio bubble.

## Metering

`api._render` calls `llm.usage.record_voice_event` (fire-and-forget) with
purpose `voice.tts`; characters land in the completion/total columns so the
admin voice dashboard keeps working.

Known seam: the events table is still owned by the LLM module. It is metering,
not synthesis, and can move to a platform metering module without touching
callers.

## Tables

| Table | Purpose |
|---|---|
| `voice_model_configs` | Admin-managed engines, encrypted keys, persona pins |
| `voices` | Public voice catalog for `/api/v1/tts/voices` |
| `tts_jobs` | Async synthesis requests for the public API |

`voice_model_configs` moved here from `llm/models.py` with no schema change —
the table name and columns are unchanged.

## Adding a provider

1. Add `app/modules/tts/engines/<name>.py` exposing
   `async def synthesize(...) -> tuple[bytes, str] | None`.
2. Dispatch it in `api._render` and map the requested container.
3. Create a `voice_model_configs` row from the admin API (`provider=<name>`).
4. Add tests for: no key, language not covered, provider failure, success.

## Adding a caller

* **Instagram / Facebook**: same Meta rules as WhatsApp — reuse the adapter
  policy, call `tts.api` directly.
* **Google reviews**: text-only today; if voice replies are added, it is the
  same call with `format=MP3`.
* **Future calls**: consume `synthesize_stream` with `format=PCM16_8K`; do not
  add a second synthesis path.

## Extraction checklist

Before this module can become its own service:

- [x] Owns its tables (`voices`, `tts_jobs`, `voice_model_configs`).
- [x] No channel imports (enforced by test).
- [x] Plain-data request/result; serializable over HTTP/gRPC.
- [ ] Metering moved out of `llm.usage` (shared table today).
- [ ] Public `/api/v1/tts` conversion implemented on top of `synthesize`
      (the endpoint is still a stub; the capability no longer is).
- [ ] Per-tenant quota wired into `synthesize` (reuse the billing budget).
