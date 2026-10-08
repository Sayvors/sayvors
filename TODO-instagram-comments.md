# Instagram comments — respond to what others post on OUR videos

Goal: the tenant's comment section becomes an inbox. Every comment on the
tenant's own IG media lands in the DB + realtime, and the tenant replies
from Sayvors. Sayvors manages the tenant's OWN account only — no acting on
other people's content.

## Current state (verified 2026-10-08)

- Parser (`meta/webhooks/parser.py:190-215`) already emits `comment.received`
  for IG (`field == "comments"`, data: `{text, media_id, from:{id}}`) and for
  FB feed (`_parse_page`, item=="comment": `{post_id, message, from}`) — both
  ledgered to MetaWebhookEvent + EventOutbox (topic `meta-events`).
- Consumer drop point: `meta/consumer.py:1179-1190` — the instagram branch
  handles only `message.received`; `comment.received` falls to a debug log.
- No comments table exists. Reply/hide/delete have no endpoint, no adapter
  method. Frontend shows comments only inside the PostModal (read-only,
  from the posts fetch `replies{...}`).

## Phase 1 — Storage + ingestion (backend)

- [ ] `ChannelComment` model in `channels/models.py` (next to ChannelMessage):
      id, channel_id FK, platform_comment_id (unique — replay dedupe),
      parent_platform_comment_id (reply threading), media_id, direction
      inbound/outbound, author_id (IGSID), author_name (username), content,
      like_count, hidden, status (received/sent/failed/hidden/deleted),
      error, created_at/updated_at. Alembic revision.
- [ ] Consumer `_handle_instagram_comment` + dispatch on `comment.received`.
      Mirrors `_handle_instagram_message`: resolve asset (provider=
      "instagram", untrusted-payload rule), dedupe by platform_comment_id —
      but an EXISTING id with different text is Meta's "edited" redelivery:
      update, don't skip. `_channel_for(platform="instagram")`, persist,
      `publish_inbox_event(type="comment")`.
- [ ] Tests `test_instagram_comments_pipeline.py`: stores a comment, Kafka
      replay does not twin, edited redelivery updates text, unknown asset
      dropped, realtime event published.

## Phase 2 — Reply / hide / delete (backend)

- [ ] `InstagramAdapter`: `reply_to_comment(comment_id, token, message)`
      (POST `/{comment-id}/replies`), `set_comment_hidden(comment_id, token,
      hidden)` (POST `/{comment-id}` hide=), `delete_comment(comment_id,
      token)` (DELETE `/{comment-id}`). Parent Page token — same credential
      path as DM sends (`get_instagram_page_credentials`).
- [ ] Meta router endpoints (tenant-scoped via MetaAsset, cache tests'
      `_seed` pattern):
      - `GET /instagram/{ig_id}/comments` — stored rows, `?media_id=` filter,
        newest first, author names enriched from contact_profiles.
      - `POST /instagram/{ig_id}/comments/{comment_id}/replies` — body
        `{message}`; send → persist outbound row (parent set, provider id
        stored) → realtime. Failure → row status "failed" + error, 502.
      - `POST /instagram/{ig_id}/comments/{comment_id}/hide` body `{hidden: bool}`.
      - `DELETE /instagram/{ig_id}/comments/{comment_id}`.
      All idempotent-safe: reply dedupes on provider message id.
- [ ] Tests: tenant isolation (other tenant's asset 404), reply persists +
      publishes, hide/delete flip state, no token → clean 4xx not 500.

## Phase 3 — Comments tab (frontend)

- [ ] `lib/api-meta.ts`: `InstagramStoredComment` type +
      fetchInstagramComments / replyToInstagramComment / setCommentHidden /
      deleteComment.
- [ ] `components/channels/instagram/CommentsTab.tsx`: list rows (avatar,
      @username, text, timeAgo, media thumbnail chip), inline reply box,
      hide/unhide + delete menus, realtime push via the existing inbox WS
      (type "comment"), unread badge on the hub tab.
- [ ] Wire into `InstagramHub.tsx` tabs; ESLint + `tsc --noEmit` clean.

## Phase 4 — AI-assisted comment replies (own round, after 1-3 ship)

- Suggest-reply endpoint (LLM: comment + media caption + business profile,
  same grounding as DM autopilot); suggest-then-send, never silent
  auto-post in v1 — public replies are reputation-risky. Per-asset opt-in
  auto-reply only after suggest mode proves itself.

## Phase 5 — Meta app config (user actions, blocks live traffic)

- [ ] Add `instagram_manage_comments` to the Meta app (App Review package).
- [ ] Verify the "Comments" webhook field is subscribed on the Instagram
      object (app-level webhooks are PER OBJECT — memory gotcha).
- [ ] Staging: `alembic upgrade head` (new revision rides the 2 pending).

## Deferred (intentionally)

- `mention.received` storage (parser emits it; needs media backfill design).
- FB Page feed comments — same table serves them; provider="facebook"
  variant of the handler when the FB hub round starts.
- Comment like_count refresh (only via posts refetch today).
