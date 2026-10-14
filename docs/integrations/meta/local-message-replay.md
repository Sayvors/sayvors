# Replaying Meta messages locally (end-to-end, without Meta)

How to exercise the **whole** inbound pipeline on your machine — ingress,
outbox, Kafka, the AI consumer, the database, the reply — for the changes that
are hard to unit-test: per-conversation context scoping and the Phase C
review→WhatsApp handoff.

Only Meta's own delivery is simulated. Every line of our code runs.

For the ngrok + real Meta test-number path see
[local-webhook-development.md](./local-webhook-development.md). That one is
higher fidelity; this one needs no Meta app, no tunnel, and no phone.

## Prerequisites

1. **Use the venv at the repo root** — `D:\code\sayvors\.venv` (or activate it
   first: `.\.venv\Scripts\Activate.ps1` from the repo root). `services/api` has
   no venv of its own, so running a bare `python` from there picks up the wrong
   interpreter — usually one missing `sentry-sdk`, `asyncpg`, `redis`,
   `aiokafka` and `openai`, which makes the whole test suite fail at import.

   To resync the environment with `pyproject.toml`:

   ```powershell
   cd D:\code\sayvors\services\api
   uv pip install -e ".[dev]"
   ```

   `uv` picks up the root `.venv` from `VIRTUAL_ENV`; if it ever resolves to a
   different environment, set `VIRTUAL_ENV` explicitly rather than letting it
   create a second one.

   Then **run the migrations** — the review-issue tables exist in no deployed
   database yet:

   ```powershell
   uv run alembic upgrade head
   ```

2. **Infrastructure.** Postgres plus the compose services:

   ```powershell
   docker compose up -d
   ```

   That brings up Redis and Kafka (`docker-compose.yml`). The reviews worker
   also needs a Google OAuth connection with a linked location for the review
   polling half — the WhatsApp half (below) does not.

3. `services/api/.env` must contain `META_APP_SECRET` (used to sign the request)
   and a working `DATABASE_URL`. Leave `RUN_BACKGROUND_WORKERS` at its default
   `true` — in dev the Kafka consumer runs in-process with uvicorn, so one
   process does everything.

4. Start the API:

   ```powershell
   make api-dev      # or: uv run -C services/api uvicorn app.main:app --port 8000
   ```

## Run the tests first

Cheaper than the replay loop, and it is the one that actually pins the fix:

```powershell
.venv\Scripts\python.exe -m pytest services/api/tests/test_conversation_context_scoping.py -v
```

These assert the prompt handed to the model contains only the writing
customer's messages — no LLM, no network, no Kafka.

## The script

`scripts/meta-local-replay.py` builds a WhatsApp cloud-API `message.received`
payload, signs it with `HMAC-SHA256(body, META_APP_SECRET)`, and POSTs it to
`/api/v1/meta/webhooks`. Stdlib only.

```powershell
python scripts/meta-local-replay.py `
  --number-id <phone_number_id> `
  --phone 15550001111 `
  --name Sara `
  --text "hi, do you deliver to Manchester?"
```

`--number-id` is the `MetaAsset.external_asset_id` for your connected number —
the consumer re-resolves the tenant from the DB and ignores the payload's
tenant claim. Get it from the `meta_assets` table.

Note the script generates a **unique wamid per send**. Reusing one is treated as
a Kafka replay and silently dropped, which looks exactly like a bug.

## Scenario 1 — context isolation (the P1 fix)

This is the "my friend was talking Arabic and now the agent talks to me in
Arabic" report.

```powershell
# Customer B writes in Arabic.
python scripts/meta-local-replay.py --number-id $NID --phone 15550002222 `
  --name Ahmed --text "مرحبا كيف حالك"

# Customer A writes in English.
python scripts/meta-local-replay.py --number-id $NID --phone 15550001111 `
  --name Sara --text "hi, do you deliver to Manchester?"

# Customer A asks again.
python scripts/meta-local-replay.py --number-id $NID --phone 15550001111 `
  --name Sara --text "and what time do you close?"
```

**Before the fix**, A's third reply came back in Arabic, because B's messages
were inside A's prompt.

**What to assert** — log level `INFO` on the API:

- A's second and third replies are in English.
- `WhatsApp thread classified` lines are per-contact and report `language=en`
  for A and `language=ar` for B. That state was *always* correct; only the
  history window was wrong.

**What to assert in the DB** — the strongest check, because it is model-
independent:

```sql
SELECT contact_phone, direction, substr(content, 1, 60)
FROM channel_messages
WHERE channel_id = '<id>'
ORDER BY created_at;
```

Every row for `15550001111` and `15550002222` is interleaved by time, but each
reply must reference only its own thread.

To see the actual prompt, temporarily log `req.messages` in `_generate_reply` —
or rely on `tests/test_conversation_context_scoping.py`, which asserts exactly
this at the provider boundary.

## Scenario 2 — review → WhatsApp handoff

1. Trigger a review that needs attention. Either let the reviews worker poll a
   real Google location, or insert one by hand so the test is repeatable:

   ```sql
   INSERT INTO review_issues
     (id, tenant_id, channel_id, review_id, rating, primary_category,
      subcategory, intent, sentiment, priority, needs_attention, status,
      reviewer_name, review_text, ticket_number, created_at)
   VALUES
     ('<uuid>', '<tenant>', '<google_channel>', 'rev-001', 1,
      'billing_payments', 'charge_reversal', 'request_refund', 'negative',
      'urgent', true, 'new', 'Sara', 'Charged twice for one order',
      'TK-000001', now());
   ```

2. Have Sara quote it:

   ```powershell
   python scripts/meta-local-replay.py --number-id $NID --phone 15550001111 `
     --name Sara --text "any update on TK-000001?"
   ```

3. **Assert**, in the API log:

   - `WhatsApp review handoff matched TK-000001 via ticket_number`
   - `WhatsApp handoff short-circuit (no LLM) ticket=TK-000001` — only if the
     ticket is `resolved`/`closed`. On a `new` ticket you should instead see a
     normal LLM reply.
   - The `review_issues.status` for that row advanced `new` → `open`.

4. To exercise the code rung rather than the ticket rung, mint one and quote it:

   ```
   POST /api/v1/reviews/issues/<issue_id>/handoff-code
   ```

   then send `K7M2QX`. Note codes are **not** currently inserted into the public
   review reply — that is deliberately unimplemented (see the design doc).

## Gotchas

- **The reply is asynchronous.** Ingress returns `200` as soon as the event is
  queued; the AI runs in the Kafka consumer afterwards. Watch the API log.
- **A stale event is skipped on purpose.** Events older than
  `_STALE_REPLY_MAX_AGE` are stored but never answered, so a replayed backlog
  does not produce a burst of replies.
- **Idempotency by wamid.** A repeated message id is dropped as a replay.
- **Escalation can silence the AI.** If the lead counter escalated the thread,
  the reply is suppressed by design — look for `WhatsApp AI handover`.
- **`GOOGLE_REVIEWS_MOCK`** short-circuits the review reply path only; it does
  not affect WhatsApp.

## Higher fidelity

Once this works, the ngrok + real Meta test-number path in
[local-webhook-development.md](./local-webhook-development.md) exercises the
same consumer with genuine Meta payloads — worth doing before shipping, since
this script's payload shape is only as good as `parser.py`'s tolerance.