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
        └── audio.py                ffmpeg container + speed conversion

app/modules/tts/router.py           public /api/v1/tts jobs + private playback
app/modules/tts/admin_router.py     voice-engine admin API (mounted by admin)
app/modules/jobs/handlers/tts_job.py  durable job -> synthesize -> private storage
```

The dependency direction is one-way: `channels → tts`. The TTS module never
imports a channel module, and `tests/test_tts_boundary.py` enforces that. The
admin router is mounted *by* `admin/router.py`; TTS itself never imports admin.

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
    speed=1.25,
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

`speed` is clamped to `0.5–2.0` and applied by `audio.convert_audio` with a
chained ffmpeg `atempo` filter in the same pass as the container conversion —
one subprocess, not one per effect. If ffmpeg is unavailable, the native audio
is returned unchanged and the degradation is logged; a speed request never
turns a usable render into a failure.

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

## Async jobs

`POST /api/v1/tts/convert` persists a pending `tts_jobs` row and enqueues a
durable `tts.job` in the same transaction. A crash cannot leave a row with no
work item or a work item with no row.

`jobs/handlers/tts_job.py` owns the lifecycle:

* A row already `completed` **with** a `storage_key` is skipped. Legacy rows
  marked completed without audio are re-rendered the next time their handler
  runs; there is no backfill for jobs that succeeded before this path existed.
* It calls `synthesize` with the row's voice, format and speed, then writes the
  bytes to the tenant's **private** docs prefix via `put_doc`, never public
  media. The key is `tts/{job.id}.{ext}`.
* It sets `storage_key`, `audio_mime`, `audio_url`, and the terminal status.
* `GET /api/v1/tts/jobs/{job_id}/audio` checks tenant ownership and streams
  from private storage. Any `storage_key` that does not start with
  `tts/{job.id}.` returns 404 without touching storage.

## Admin routes

Voice-engine administration lives in `tts/admin_router.py`. `admin/router.py`
mounts it with the admin auth and admin rate-limit dependencies:

```python
admin_router.include_router(
    tts_admin_router,
    dependencies=[Depends(require_admin), Depends(admin_rate_limit)],
)
```

This keeps the arrow `admin → tts`; the capability stays extractable, and the
platform-admin UI stays in `apps/admin`, never in `apps/web`.

## Failure contract

* Provider network/quota/malformed-response errors are caught, logged and
  metered as `failed`; `synthesize` returns `None`.
* Missing API key, unsupported language, no enabled engine → `None` without an
  error log (expected states).
* Conversion failure is not fatal: the native audio is returned with its real
  container so the channel can still send a plain audio bubble.
* The async job has two failure classes. **No rendered audio** is a terminal
  domain failure: the `tts_jobs` row becomes `failed` and is not retried,
  because retrying a deterministic provider answer only spends money again.
  **A storage or infrastructure error** is recorded and re-raised so the job
  runner retries it.
* `synthesize` returns `None` for provider failures, so the handler cannot tell
  a transient outage from a deterministic one. It treats both as a terminal
  domain failure. The unified job still succeeds — voice is an optional
  enhancement, not the job's contract.

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
| `tts_jobs` | Async synthesis requests, speed, private `storage_key` + `audio_mime` |

`voice_model_configs` moved here from `llm/models.py` with no schema change —
the table name and columns are unchanged. `tts_jobs.storage_key` and
`audio_mime` were added by an idempotent migration
(`ADD COLUMN IF NOT EXISTS`) so the deploy is safe on a database that already
has them.

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
- [x] Public `/api/v1/tts` conversion implemented on top of `synthesize`
      (durable job + private playback).
- [x] Admin voice routes co-located with the capability, mounted by admin.
- [x] Rendered audio uses tenant-private docs storage, not public media.
- [ ] Metering moved out of `llm.usage` (shared table today).
- [ ] Per-tenant quota wired into `synthesize` (reuse the billing budget).
- [ ] Job submission no longer imports the shared `jobs` module (needs a queue
      client or an HTTP submit inside the extracted service).
