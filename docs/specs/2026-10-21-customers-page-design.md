# Customers Page — Design

Date: 2026-10-21
Status: Approved (user said "build it")
Related: inbox threads, leads, Google reviews, conversation categorization

## Goal

A single dashboard surface where a tenant sees **every person they have ever
had contact with** — across WhatsApp, Instagram, Facebook, and Google
Business Profile — as a table, and can click any row to open that person's
complete profile: identity, categorization, captured lead info, full
conversation timeline, and (for Google reviewers) the reviews and our
replies.

Today those people are scattered across the inbox (grouped by thread),
the leads board (only those the AI captured), and the reviews page. The
customer page is the unified view of the same data.

## Non-goals

- Cross-platform person merging. A WhatsApp number and an Instagram handle
  for the same human stay separate rows unless the tenant links them
  manually. Auto-merge by name is a trap (two "Ahmed"s become one
  person). Manual linking is a v2.
- A new data model. Everything already exists; this is aggregation + UI.
- New categorization. The `important` flag shipped 2026-10-20 (see
  `docs/architecture/conversation-categorization.md`) is the headline
  column. Chat categorization is keyword-based and stays that way; the
  LLM review engine already classifies Google reviews.

## Identity model

A **customer is a thread** — `(channel_id, contact_phone_hash)` — the
same grouping the inbox already uses. One row = one person on one channel.
Google reviewers became individual threads in the 2026-10-20 change, so a
Google review and a WhatsApp conversation are the same kind of row.

Per-platform rows means the table can show the same human twice (once per
channel they touched). That is correct and safe.

## Data sources (all existing)

| Source | Model | Provides |
|---|---|---|
| Inbox threads | `ChannelMessage` grouped by `(channel_id, contact_phone_hash)` | identity (name, phone, avatar), platform, channel, last message, count, unread, category, priority, important, can_reply |
| Contact profile | `ContactProfile` (tenant, platform, contact_id) | name, username, avatar, fetched_at |
| Lead | `Lead` (channel_id, contact_id) | stage, intent, request, summary, captured facts + provenance, opt_out, last_message_at |
| Google review | `ReviewReply` (channel_id, review_id) | rating, review text, our reply, reply status, timestamps |

## Backend

Two endpoints, both reusing existing queries — no new tables, no
migrations.

### `GET /api/v1/customers`

Wraps `list_inbox_threads` (already returns identity, category, priority,
important, can_reply, platform, channel_name, last_message, last_message_at,
message_count, unread, is_unknown) and augments each row with:

- `lead_stage: str | None`
- `intent: str | None`
- `has_review: bool` (true when any `ReviewReply` exists for that thread's
  channel + the reviewer's identity)
- `contact_username`, `avatar_fetched_at` from `ContactProfile`

Filters: `search`, `platform`, `category`, `priority`, `important`
(boolean), `limit`, `offset`. Sorted by **important first, then last
contact newest-first** — the whole point is "who needs me now".

Response shape: `CustomerListResponse { customers: Customer[], total: int }`.

### `GET /api/v1/customers/{channel_id}/{contact_key}`

Full profile. Returns:

- `identity`: name, username, avatar_url, contact_phone, platform, channel_name, contact_id, profile_fetched_at
- `category`, `priority`, `important`
- `lead`: the full `Lead` row (or null) — stage, intent, request, summary, captured facts, field_provenance, opt_out, last_message_at, next_action_at, priority, priority_since, ai_miss_count
- `messages`: all `ChannelMessage` rows in the thread (oldest first), decrypted
- `reviews`: list of `ReviewReply` for that reviewer (rating, text, reply_text, status, timestamps) — only for Google review threads
- `can_reply: bool`

Resolution: `contact_key` == `UNKNOWN_THREAD_KEY` ("unknown") means the
catch-all thread (no contact_phone). Otherwise it is the contact phone
(or the `google:<digest>` synthetic key for a reviewer).

## Frontend: `/dashboard/customers`

A table, not cards. Columns:

| Name | Platform | Channel | Category | Priority | Last contact | Messages | Unread |

- Sortable: last contact, priority (important-first), message count.
- Filters at the top: search input, platform dropdown, category dropdown,
  priority dropdown, "Important only" chip.
- Click a row → a side panel (not a new route) with the complete
  profile. The table stays visible so the tenant can click through people
  without losing their place.
- Side panel tabs: **Profile** (identity + categorization + lead facts),
  **Conversation** (messages timeline + send box, only when `can_reply`),
  **Reviews** (only for Google review threads).

## Side panel — "Profile" tab

- Identity card: avatar, name, username, platform badge, phone/identity,
  channel name, profile-fetched-at.
- Categorization: category badge, priority badge, "Important" badge with
  the reason, and the **manual category/priority override** (this is where
  the existing `PATCH /threads/{channel_id}/{contact_phone}/category`
  endpoint finally gets a UI).
- Lead block: stage chip, intent, request, summary, captured facts
  (phone/email/address/vertical/website) with provenance, opt_out flag,
  last_message_at, next_action_at. Deep link to the Leads board.
- "Open in inbox" deep link to `/dashboard/channels/inbox?channel=...&key=...`.

## Side panel — "Conversation" tab

- All messages oldest-first, decrypted, with timestamps.
- Send box only when `can_reply` (disabled with an explanation for
  Google review threads: "answered from the Reviews page").

## Side panel — "Reviews" tab

- Only rendered for Google review threads.
- Rating, review text, author, created_at.
- Our reply (reply_text, status, timestamps) or "Not replied yet".

## Navigation

Add to `MAIN_ITEMS` in `Sidebar.tsx`, next to Inbox:

```
{ key: "customers", icon: <...>, href: "/dashboard/customers" }
```

Page file: `apps/web/app/dashboard/customers/page.tsx` (thin wrapper like
`leads/page.tsx`).

## What we are deliberately not doing

- No cross-platform person merging (v2: "link accounts").
- No new data model, no migrations.
- No new categorization — the `important` flag is reused.
- No LLM-based chat categorization (the keyword path stays as-is; that is
  a separate, larger piece).

## Success criteria

1. A tenant can see every person they've had contact with, on every
   platform, in one table.
2. Clicking a row opens a profile showing identity, categorization, lead
   facts, full conversation, and (for Google) reviews + our replies.
3. The "Important" filter shows the same set of people the inbox's
   "Important" filter shows — one rule, both surfaces.
4. A Google review is a first-class row with its own thread, not a line
   in the "unknown" bucket.
5. The manual category override works from this page.
6. `npx tsc --noEmit` and `npm run build` pass; backend tests pass.