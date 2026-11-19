# Google Reviews per-review concurrency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the serial per-review loop from the Google Reviews poll so 100 reviews on one channel take ~1 minute instead of ~5-13, with no change to notifications, statistics, idempotency or the channel claim.

**Architecture:** `_handle_fetched_review` is left untouched — it is ~200 lines of stateful logic with hundreds of tests pinned to it. Instead, `process_channel` is given a helper that runs each review in its own DB session and its own Google client under one process-wide bounded semaphore, then merges the per-review stats into the channel stats. A per-event-loop semaphore key keeps the bound global without changing any call signature. The serial path remains for tests that need it via the injectable session factory.

**Tech Stack:** Python 3.x, asyncio, SQLAlchemy async sessions, pytest-asyncio, SQLite in-memory test DB.

---

## File map

- Modify `services/api/app/modules/channels/reviews_worker.py` — constants, injectable session factory, per-review client builder, concurrent review loop, extract `_process_reviews`.
- Modify `services/api/tests/conftest.py` — point the new `_session_factory` at `TEST_SESSION` (one line, same pattern as the billing session overrides).
- Test `services/api/tests/test_reviews_worker.py` — new focused tests for concurrency, stats merge, exception accounting, and unchanged end-to-end behaviour.
- Update `readiness-report.html` — record the throughput fix.

## Decisions locked in

- **No job lane.** A durable queue would make replies asynchronous and change poll totals. Decided against; the claim + unique indexes + advisory lock already make replay safe.
- **Global bound.** `_REVIEW_CONCURRENCY = 10` is a named constant with a reason, not a magic number. One semaphore per event loop, held in a `WeakKeyDictionary`, so the cap spans all channels and all callers (`poll_once`, Pub/Sub push, direct tests) without changing function signatures.
- **Own session and client per review.** `_handle_fetched_review` commits/rolls back internally and uses advisory locks; sharing the channel's session across concurrent tasks is unsafe. Each task reloads `Channel` and `AutoReplyConfig` by id in its own session and builds its own client with a persister bound to that session.
- **Stats merge, no re-raise.** Each task returns its own stats dict; exceptions are logged with the review id and counted in `errors`. One bad review no longer fails the whole channel pass — the previous serial path effectively had the same behaviour because `_handle_fetched_review` already caught its own failures.

---

### Task 1: injectable session factory + constants

**Files:** `services/api/app/modules/channels/reviews_worker.py`

- [ ] Add imports: `weakref`, `AsyncIterator` from `collections.abc` if needed.
- [ ] Add `_REVIEW_CONCURRENCY = 10` with a comment explaining the ceiling (five channels × two reviews each is the prior effective parallelism; ten bounds LLM fan-out while removing the 100-review wall).
- [ ] Add `_session_factory = None` at module scope. Helper `_review_session()` returns `_session_factory()` when set, else the module's existing `async_session` imported lazily (preserves the existing monkeypatch in `test_poll_once_sums_every_channel_field`).
- [ ] Add `_review_semaphore()` using `weakref.WeakKeyDictionary` keyed by the running loop.
- [ ] Run `python -c "import app.modules.channels.reviews_worker"` to confirm import.

### Task 2: per-review client builder

**Files:** `services/api/app/modules/channels/reviews_worker.py`

- [ ] Extract the client setup currently at lines 1628-1662 into `_make_review_client(access_token, refresh_token, expires_at, channel_id, session) -> GoogleReviewsClient`. It decrypts nothing (tokens are passed in decrypted), sets known expiry, and installs a persister that writes the refreshed token to the given session with the same error logging as today.
- [ ] In `process_channel`, keep the existing outer client construction for `list_reviews`, backfill, location metadata and the sweep. Per-review tasks call the new builder with the same decrypted tokens.

### Task 3: extract `_process_reviews` and run concurrently

**Files:** `services/api/app/modules/channels/reviews_worker.py`

- [ ] Create `async def _process_reviews(db, channel, config, client, reviews, stats, access_token, refresh_token) -> None`.
- [ ] Inside, define `_one(review)`: acquire the loop semaphore; open `_review_session()`; `await sdb.get(Channel, channel_id)` and `await sdb.get(AutoReplyConfig, config_id)`; build a per-task client; call `await _handle_fetched_review(sdb, ch, cfg, task_client, review, task_stats)`; return the stats.
- [ ] `results = await asyncio.gather(*[_one(r) for r in reviews], return_exceptions=True)`.
- [ ] Merge numeric keys into the caller's `stats`; log exceptions with the review id and increment `stats["errors"]`.
- [ ] Keep the claim-renewal cadence: renew after every 10 *completed* reviews, matching today's `for` loop.
- [ ] Replace the two serial `for review in ...: await _handle_fetched_review(...)` loops (incremental at :1745 and sweep heal at :1789) with `_process_reviews(...)`.
- [ ] Run `pytest tests/test_reviews_worker.py -q -n 0` — all existing tests must pass unchanged.

### Task 4: test the new behaviour

**Files:** `services/api/tests/conftest.py`, `services/api/tests/test_reviews_worker.py`

- [ ] In `conftest._test_billing_sessions`, also `monkeypatch.setattr(reviews_worker, "_session_factory", TEST_SESSION, raising=False)` so per-review sessions hit the test DB.
- [ ] Test concurrency: patch `_handle_fetched_review` with a function that increments an active counter, awaits an `asyncio.Event`, and records the peak; feed two reviews to `_process_reviews` and release the gate once both are in flight. Assert peak == 2.
- [ ] Test bound: set the module semaphore to a fresh `asyncio.Semaphore(1)` and assert the peak is 1 with two reviews.
- [ ] Test stats merge: patch `_handle_fetched_review` to set `stats["new"] += 1` and `stats["replied"] += 1`; feed three reviews; assert the caller's stats show 3 and 3.
- [ ] Test failure isolation: patch one review to raise; assert the other review still ran and `stats["errors"] == 1`.
- [ ] Run the full `test_reviews_worker.py` file again.

### Task 5: verify, document, commit

- [ ] Full backend suite (model/session-factory change makes this cross-cutting): `python -m pytest -q`.
- [ ] Update `readiness-report.html` with the throughput fix and the measured/expected envelope.
- [ ] Commit code and docs separately; never push.
