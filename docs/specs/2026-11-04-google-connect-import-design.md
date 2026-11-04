# Google connect import + AI draft workspace

Date: 2026-11-04

## Problem

Connecting Google Business Profile creates the channel rows and returns to the
dashboard, but the first review import is invisible: the normal poll runs at
most every five minutes, historical reviews are only drafted if the channel's
auto-reply settings allow it, and there is no progress state. A merchant with
several locations and a long review history has no idea whether the import is
running, how many reviews were found, or which ones still need a reply.

## Scope

A first-connect flow that:

- imports every review for every connected Google location immediately,
- shows a persistent modal with per-location and per-review progress,
- generates AI drafts for unanswered reviews inside a merchant-selected range,
- never publishes without an explicit merchant action,
- supports publish-selected and publish-all,
- survives closing the modal, navigation and page reload,
- ends with a factual summary and a link to Analytics.

Reviews outside the selected range are still imported and counted. They show
`No draft — outside selected range` and can be drafted individually later.

## Lifecycle

```
connect callback
  -> create session (queued)
  -> worker fetches all reviews (fetching)
  -> session awaits scope (awaiting_scope)
  -> merchant picks 30d / 6m / 12m / all, clicks Generate
  -> worker generates drafts (generating)
  -> session ready
  -> merchant publishes selected/all (publishing)
  -> worker publishes to Google
  -> session completed with summary
```

If a session is closed with `Run in background`, the floating progress button
reopens the same session. If the scope has not been chosen yet, the button says
"Setup needed" and reopens the scope selector.

## Data model

### `connect_import_sessions`

- `id`, `user_id`
- `status`: queued | fetching | awaiting_scope | generating | ready | publishing | completed | failed
- `scope_days`: 30 | 180 | 365 | 0 (all time)
- `total_locations`, `fetched_locations`
- `total_reviews`, `fetched_reviews`
- `total_drafts`, `drafts_ready`, `drafts_failed`
- `locked_until` for multi-worker claiming
- `summary` JSON, `error` text
- timestamps

### `connect_import_events`

Append-only, plain-language progress feed for the modal, one row per
worker/merchant action.

- `id`, `session_id` (cascade delete)
- `level`: info | success | warning | error
- `message`
- `created_at`, indexed with `session_id`

Events are persisted so the chronological story survives closing the modal,
navigation, reload and worker hand-off. The API returns the newest 120 in
ascending order.

### `connect_import_items`

One row per review in the session.

- `id`, `session_id`, `channel_id`, `review_id`
- display snapshot: `location_name`, `reviewer_name`, `rating`, `review_text`, `review_time`
- `status`: pending | generating | draft_ready | already_replied | outside_scope | failed | selected | published | publish_failed
- `reply_id` (the `review_replies` row holding the draft)
- `selected` boolean
- `error` text
- unique `(session_id, channel_id, review_id)`

Drafts live in the existing `review_replies` table with
`status = pending_approval`, so they remain in Outbox even if the merchant
closes the modal. Publishing updates those rows to `posted`.

## Worker

A dedicated `run_connect_import_worker` loop, separate from live review
polling:

- claims sessions with `locked_until` (crash-safe lease),
- fetches reviews per location with a bounded concurrency,
- generates drafts with a per-session semaphore (3) and a global semantic
  (8), so ten tenants cannot starve each other or live auto-replies,
- retries per review, recording the failure on the item,
- publishes selected drafts with a per-session semaphore and `confirm_reply_live`,
- updates counters and the final summary in the same transaction as each
  state change.

Reviews already having `pending_approval`, `posted` or `approved` replies are
marked `already_replied` and never re-drafted.

## API

All routes are tenant-scoped and require `channels.view` / `channels.edit`.

- `GET /api/v1/channels/google/import-sessions/{id}`
  - session counters, locations, items, events, summary
- `POST /api/v1/channels/google/import-sessions/{id}/start`
  - body `{ scope_days }`, only from `awaiting_scope`
- `POST /api/v1/channels/google/import-sessions/{id}/publish`
  - body `{ review_ids?: string[], all?: boolean }`, only from `ready`
- `GET /api/v1/channels/google/import-sessions/latest`
  - the active session for the tenant, for reload/background restore

The Google callback creates the session after the channel rows commit and
redirects with `import_session=<id>`.

## UI

### Modal

Header: overall progress, location/review/draft counts.

The body is split into a main column and a 300px progress panel. The panel is
a plain-language, mostly-gray chronological feed (reviews found per location,
reply ready or needs another try, location finished, posting result, done).
It avoids technical wording, exception text and timestamps so a non-technical
merchant sees reassurance rather than a log. On mobile it moves above the
workspace. Surfaces use compact radii (8px cards, 6px buttons, 4px chips and
status tags) instead of the previous pill-heavy layout.

Step 1 — import:
- per-location sections with fetch and draft counts
- progress bar while fetching

Step 2 — scope:
- radio options: Last 30 days, Last 6 months, Last 12 months, All time
- default 6 months
- warning for 12 months/all time: more time and AI usage
- button `Generate drafts`

Step 3 — review workspace:
- filter chips: All, Needs reply, Draft ready, Already replied, Failed
- review rows: reviewer, rating, text, status, generated draft preview, checkbox
- outside-scope rows show `Generate draft` per row (future action; the initial
  release shows the label)
- footer: `Run in background`, `Publish selected (N)`, `Publish all drafts`

Step 4 — summary:
- unanswered before / published now / already answered / failed
- oldest location age
- review volume for the last 12 months
- rating-over-time mini chart
- `View full analytics`
- modal closes and the floating button clears

### Floating progress

A client component mounted in the dashboard layout:

- reads the active session id from localStorage and the latest-session endpoint
- fixed on the right edge, opposite the sidebar
- circular percentage + status text
- click reopens the modal
- hidden when the session is completed or failed and acknowledged

## Error states

- No Google locations / no reviews: honest empty state, no fake progress.
- No model configured: items fail with `No model configured`; summary explains.
- Google 403/429: per-location or per-review error, retry safe.
- Session worker crash: lease expires, another worker resumes pending items.
- Publish failure: item `publish_failed`, reply row `failed`, error visible.
- Reload with a stale session: latest-session endpoint returns it only while
  status is not completed/failed; otherwise the launcher clears it.

## Testing

- model/migration: session + item uniqueness, cascade.
- fetch: all reviews counted, already-replied detected, scope status applied.
- generation: bounded concurrency, draft row created, failure recorded.
- publish: selected only, `all`, Google error leaves `publish_failed`.
- endpoints: tenant isolation, invalid status transitions, summary shape.
- events: per-location collection, draft ready/failed, publish success/failure
  and completion rows; event ordering in the API response.
- frontend: typecheck + build; modal state transitions and launcher persistence
  covered by a small unit test where practical.
