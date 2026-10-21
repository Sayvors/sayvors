# Speech-to-Text (STT) — Unified Publish Pipeline

## Overview

Sayvors can transcribe any audio from any channel into text using
[**faster-whisper**](https://github.com/SYSTRAN/faster-whisper) — a fast,
CTranslate2-based reimplementation of OpenAI's Whisper model. This is not
hardcoded to any platform: WhatsApp voice notes, Instagram voice messages,
Facebook voice notes, Telegram voice messages, Google voice posts, user
uploads, or any audio URL can be transcribed.

## How it works

### Data flow

1. **Client calls** `POST /api/v1/channels/stt` with `{ audio_url, language }`.
2. An `STTJob` row is created with status `pending` and an idempotent
   `post.publish` job is enqueued on the `publishing` lane.
3. The job runner picks up the job, downloads the audio from `audio_url`,
   transcribes it with faster-whisper, and writes the transcript +
   confidence + duration back to the `STTJob` row.
4. The client polls `GET /api/v1/channels/stt/jobs/{job_id}` until
   `status == "completed"` and reads `text`.

### Architecture

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Client    │────▶│   POST /stt      │────▶│   STTJob row    │
│             │     │   (create job)   │     │   (pending)     │
└─────────────┘     └──────────────────┘     └─────────────────┘
                                              │
                                              ▼
                                      ┌─────────────────┐
                                      │  Job runner     │
                                      │  (claims job)   │
                                      └─────────────────┘
                                              │
                                              ▼
                                      ┌─────────────────┐
                                      │  faster-whisper │
                                      │  (CTranslate2)  │
                                      └─────────────────┘
                                              │
                                              ▼
                                      ┌─────────────────┐
                                      │   STTJob row    │
                                      │   (completed)   │
                                      └─────────────────┘
```

### Idempotency

Every STT job has a unique `job_id` in its payload. The job runner checks
terminal status before running, so the same job is never transcribed twice.
Calling `POST /stt` with the same audio twice creates two jobs and two
transcriptions — dedup by `stt_job_id` is the caller's responsibility if
desired.

## Configuration

All settings live in `services/api/app/config.py` under `Settings`:

| Setting | Default | Meaning |
|---------|---------|---------|
| `STT_MODEL` | `base` | Whisper model size: `tiny`, `base`, `small`, `medium`, `large-v1`, `large-v2`, `large-v3` |
| `STT_DEVICE` | `cpu` | `cpu`, `cuda`, or `auto` |
| `STT_COMPUTE_TYPE` | `int8` | `int8`, `int8_float16`, `float16`, `float32` |
| `STT_BEAM_SIZE` | `5` | Beam size for decoding |
| `STT_VAD_FILTER` | `true` | Voice activity detection — skips silent segments |
| `STT_MAX_FILE_MB` | `100` | Max audio file size for transcription |

Example `.env`:

```env
STT_MODEL=small
STT_DEVICE=cpu
STT_COMPUTE_TYPE=int8
STT_BEAM_SIZE=5
STT_VAD_FILTER=true
```

On a CPU, `base` with `int8` is fast enough for short voice notes. On a GPU
(CUDA), switch to `STT_DEVICE=cuda` and `STT_COMPUTE_TYPE=float16` for
faster transcription of longer audio.

## API

### `POST /api/v1/channels/stt`

Create an STT job:

```http
POST /api/v1/channels/stt
Content-Type: application/json

{
  "audio_url": "https://cdn.example.com/voice-note.ogg",
  "language": "en"
}
```

Response:

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "text": null,
  "confidence": null,
  "duration_ms": null,
  "error": null,
  "created_at": "2026-10-21T14:30:00+00:00"
}
```

### `GET /api/v1/channels/stt/jobs`

List your STT jobs (most recent first):

```http
GET /api/v1/channels/stt/jobs?limit=20&offset=0
```

### `GET /api/v1/channels/stt/jobs/{job_id}`

Get one job's result:

```http
GET /api/v1/channels/stt/jobs/550e8400-e29b-41d4-a716-446655440000
```

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "text": "Hello, can you hear me?",
  "confidence": 0.94,
  "duration_ms": 2340,
  "error": null,
  "created_at": "2026-10-21T14:30:00+00:00"
}
```

If transcription failed:

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "failed",
  "text": null,
  "confidence": null,
  "duration_ms": null,
  "error": "faster-whisper model load failed: ...",
  "created_at": "2026-10-21T14:30:00+00:00"
}
```

## Deployment

### Install dependency

```bash
pip install faster-whisper
```

The dependency is already declared in `services/api/pyproject.toml` as
`faster-whisper>=1.0`.

### Model download

The first time a transcription runs, faster-whisper downloads the model
weights from Hugging Face (~80 MB for `tiny`, ~150 MB for `base`,
~500 MB for `small`). Subsequent runs reuse the cached model. The model
is cached in `~/.cache/huggingface/hub` by default.

On a machine without internet at runtime, pre-download the model:

```bash
python -c "from faster_whisper import WhisperModel; WhisperModel('base')"
```

### Workers

The STT job runs on the `publishing` lane. If you run a dedicated worker
container (`docker-compose.prod.yml` worker service), it picks up STT jobs
automatically. You can scale workers with `docker compose --scale worker=N`
to transcribe multiple audio files in parallel.

## Limitations

- **Audio length**: No hard limit, but very long audio (>30 min) will take
  proportionally longer and use more memory. Consider `STT_MODEL=tiny` or
  `small` for long recordings on CPU.
- **Languages**: Whisper supports ~100 languages. Set `language` to the
  expected language (ISO 639-1 code, e.g. `"en"`, `"ar"`, `"zh"`) for
  better accuracy; omit it for auto-detection.
- **Real-time streaming**: Whisper is batch-oriented, not streaming. For
  live transcription you need a different architecture (VAD + chunking).

## Related

- `docs/architecture/conversation-categorization.md` — how transcribed
  text feeds into categorization and prioritization
- `services/api/app/modules/stt/` — all STT code (models, router,
  service, provider)