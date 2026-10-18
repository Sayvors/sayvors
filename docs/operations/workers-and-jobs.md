# Worker and Job Operations

The API can run background loops in its own process for local development. In
the production Compose topology, HTTP serving and background work are split:
the API is configured with `RUN_BACKGROUND_WORKERS=false`, and a dedicated
worker container runs `python -m app.workers` using the API image and settings.
See [API configuration](../api/configuration.md).

## Start a worker

From `services/api`, with the API dependencies and the deployment's database,
Redis, Kafka, and provider configuration available:

```powershell
python -m app.workers
```

The worker warms up its dependencies, starts selected background loops, and
drains the transactional outbox. It handles Ctrl+C in local Windows
development and SIGINT/SIGTERM in container deployments. Keep secrets in the
environment or deployment secret manager; do not copy a developer `.env` into
an image or commit it.

In a split deployment, keep `RUN_BACKGROUND_WORKERS=false` on the API so the
API lifespan does not start the same queue/poll loops. The worker entrypoint
still runs its loops if that setting is false on the worker, but emits a
warning; configure the API and worker services intentionally.

## Select worker loops

By default, the worker starts every registered loop. To run a subset, set
`WORKER_LOOPS` to a comma-separated allowlist:

```dotenv
WORKER_LOOPS=meta-events-ai-replies,lead-actions
```

Current names are:

- `google-reviews-auto-reply`
- `localith-sync`
- `post-publisher`
- `analytics-consumer`
- `performance-sync`
- `messaging-rollup`
- `meta-events-ai-replies`
- `lead-actions`
- `job-runner-realtime`
- `job-runner-publishing`
- `job-runner-media`
- `job-runner-bulk`
- `escalation-sweeps`
- `lead-digest`

An unknown name fails startup rather than silently running no workers. The
outbox drainer starts alongside the selected loops and is not selected through
`WORKER_LOOPS`.

## Unified job lanes

The unified job registry currently maps types to these lanes:

| Lane | Work types | In-process concurrency |
|------|------------|------------------------|
| `realtime` | Meta message replies and template sends | 8 |
| `publishing` | Google post and media publishing | 4 |
| `media` | Media processing | 2 |
| `bulk` | Databank ingest, URL scrape, speech-to-text, text-to-speech | 1 |

Workers poll PostgreSQL for due jobs, claim rows with `FOR UPDATE SKIP LOCKED`,
and use expiring leases so jobs can be reclaimed after a worker crash. Kafka
dispatch topics wake/coordinate lane workers; PostgreSQL remains the persisted
job lifecycle. A job with a caller-provided idempotency key is deduplicated
within its tenant.

## Status and troubleshooting

Job statuses include `accepted`, `queued`, `running`, `retrying`, `blocked`,
`succeeded`, `failed`, `cancelled`, and `dead`. Transient handler failures are
retried with backoff until the attempt limit; terminal failure and exhausted
retries require operator attention. A worker crash can leave work running
until its lease expires and another poll can claim it.

Check the worker logs for dependency startup failures, lane names, handler
errors, and job identifiers. Check `/health`, `/api/v1/redis/health`, and
`/api/v1/kafka/health` for API/dependency status. A successful HTTP health
check does not prove that a separate worker is running.

There is not one generic customer-facing job-inspection endpoint for every job
type. Use the operation-specific status routes: the publishing API returns a
job ID that can be polled at
`GET /api/v1/channels/publish/{job_id}`; RAG, TTS, and STT expose their own job
lists and per-job endpoints. See the [API endpoint reference](../api/endpoints.md).

If work is stuck:

1. Confirm the worker process is running and that its `WORKER_LOOPS` selection
   includes the relevant loop/lane.
2. Check API and worker logs for PostgreSQL, Redis, Kafka, provider, or handler
   errors.
3. Confirm the job type is registered and a handler exists for that type.
4. For RAG ingestion, inspect the RAG job/document state and use the documented
   retry operation when appropriate.
5. For external publishing or messaging, verify provider connection and
   permissions before retrying. A process may have stopped after an external
   provider accepted an action; check the destination before manually
   resubmitting to avoid duplicate side effects.

Do not treat Kafka topic contents as the authoritative job state. Do not
delete job or outbox rows to clear a backlog; first identify why the consumer
or handler is not progressing.
