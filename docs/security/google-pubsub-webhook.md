# Google Reviews Pub/Sub Push — Ingress Guard

How the realtime review-pull ingress is implemented now: Google Business
Profile publishes review notifications to a Cloud Pub/Sub topic, and a push
subscription delivers them to this API. This document describes what the
endpoint trusts, what it rejects, and why the rest of the system stays
correct even when a push is lost, forged, or duplicated.

## Where it lives

| Piece | Location |
|---|---|
| Endpoint | `POST /api/v1/channels/google/pubsub` — `channels/router.py` |
| Verification + parsing + pull spawn | `app/modules/channels/google_push.py` |
| Config | `GOOGLE_PUBSUB_PUSH_AUDIENCE`, `GOOGLE_PUBSUB_PUSH_EMAIL` (`app/config.py`) |
| Pull pipeline | `channels/reviews_worker.py` (`_poll_one_channel` → `process_channel`) |

## The three-layer pull design

1. **Push (≈ seconds).** This endpoint. Accelerates discovery only.
2. **Incremental poll (≤60s).** `google-reviews-auto-reply` worker loop;
   cursor advances only after a real fetch, fetch window overlaps 15 min.
3. **Daily sweep heal (≤24h).** The daily full read imports any review that
   has no inbox row, through the same pipeline as live reviews
   (`SWEEP_HEAL_BATCH` caps the import per pass).

Google documents Business Profile notifications as **best-effort
delivery**. Layers 2 and 3 are the correctness guarantee; the push layer
must never be treated as required for completeness. Removing the poll loop
because "the webhook exists" would silently lose reviews.

## Verification (fail-closed)

Every request is rejected unless all of these hold:

1. **Configured audience.** `GOOGLE_PUBSUB_PUSH_AUDIENCE` must be set.
   Without it the endpoint answers `503` to everything — a deployment with
   no push subscription has no tokens worth trusting.
2. **OIDC bearer token.** The `Authorization: Bearer` JWT is verified with
   `google.oauth2.id_token.verify_oauth2_token` against Google's public
   keys: signature, expiry, and `aud == GOOGLE_PUBSUB_PUSH_AUDIENCE` (the
   audience configured on the push subscription). Any failure ⇒ `403`.
3. **Identity pin (optional but recommended).** With
   `GOOGLE_PUBSUB_PUSH_EMAIL` set, a correctly-signed token minted by any
   other Google identity is rejected. Set it to the dedicated service
   account attached to the push subscription.

Flood control mirrors the Meta webhook posture: a per-IP Redis rate limit
(600/min, fail-closed) and a 64 KB body cap before the body is read.
`TESTING=true` skips only the rate limit, never verification.

## Payload handling — least trust

The Pub/Sub envelope is `{message: {data: <base64 JSON>}}`. Parsing is
defensive at every step; anything unrecognizable is logged and **acked
200** (`{"status": "ignored"}`) rather than 5xx'd — a 5xx makes Pub/Sub
retry byte-identical garbage forever, and the poll layer loses nothing by
the drop.

Only one thing is ever read from the notification: **the location id**
(from the `location`/`review` resource names or a bare `locationId`).
Review content in a push is never trusted or stored. The id selects
channels by the indexed `listing_key` column, and each matched **active**
channel gets a targeted pull that re-fetches the full review state from
Google. A forged notification can therefore only cause a read of the
attacker-chosen location's public reviews into the tenant that already
connected that location — no data injection, no cross-tenant write.

## Duplication and races

- A push and the poll worker can race on the same channel: both paths go
  through the atomic per-channel claim (`polling_locked_until`), so one
  wins and the other no-ops.
- Duplicate pushes re-run an idempotent pipeline (unique
  `platform_message_id`, replied-checks, read-back confirmation before
  `posted`), so at worst they replay cheap read paths.
- Spawned pulls are bounded: 5 concurrent, 200 queued. Beyond the queue
  cap the pull is dropped deliberately — the 60s poll fetches the review
  anyway. Unbounded task growth would silently eat memory instead.

## Invariants

- No configured audience ⇒ no accepted push, ever.
- Every stored review row traces to a Google API fetch, never to push
  payload content.
- The endpoint never blocks on the pull: it acks after spawning; a pull
  failure is logged and healed by the poll/sweep layers.
- Legacy route `POST /api/v1/channels/webhook/{platform}` remains
  `410 GONE`; this endpoint is the only Google ingress.
