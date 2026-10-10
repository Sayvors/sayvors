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

## Phase 1 — Storage + ingestion (backend) — DONE 2026-10-10

- [x] `ChannelComment` model in `channels/models.py` (next to ChannelMessage):
      id, channel_id FK, platform_comment_id (unique — replay dedupe),
      parent_platform_comment_id (reply threading), media_id, direction
      inbound/outbound, author_id (IGSID), author_name (username), content,
      like_count, hidden, status (received/sent/failed/hidden/deleted),
      error, **platform_timestamp** (when it was written on Instagram),
      **deleted_at** (see below), created_at/updated_at. Alembic revision.
      Deletion lifecycle: Meta sends NO delete webhook — deleted-on-IG is
      detected lazily (probe the comment id, 404 → deleted_at set);
      deleted-via-Sayvors sets it immediately.
- [x] Consumer `_handle_instagram_comment` + dispatch on `comment.received`.
      Mirrors `_handle_instagram_message`: resolve asset (provider=
      "instagram", untrusted-payload rule), dedupe by platform_comment_id —
      but an EXISTING id with different text is Meta's "edited" redelivery:
      update, don't skip. `_channel_for(platform="instagram")`, persist,
      `publish_inbox_event(type="comment")`.
- [x] Tests `test_instagram_comments_pipeline.py` (5 passing): stores with
      platform truth, Kafka replay does not twin, edited redelivery updates
      text + realtime "comment_updated", unknown asset dropped, timestamp
      parser tolerates junk/naive.

## Phase 2 — Reply / hide / delete (backend) — DONE 2026-10-10

- [x] `InstagramAdapter`: `reply_to_comment` / `set_comment_hidden` /
      `delete_comment` — writes PROPAGATE MetaAPIError (a failed reply
      must surface, never silently vanish like an unreadable read).
- [x] Meta router endpoints (shared `_instagram_asset_or_404` — the tenant
      boundary is the 404):
      - `GET /instagram/{ig_id}/comments` — stored rows only (never Graph,
        never rate limit), `?media_id=` + `?limit<=200`, contact_profiles
        fallback for missing author names.
      - `POST .../comments/{comment_id}/replies` — send → store → realtime;
        Meta failure = 502 AND a failed row in the thread (visible,
        retryable).
      - `POST .../comments/{comment_id}/hide` (body {hidden}) — Meta's rule:
        hidden stays visible to its author.
      - `DELETE .../comments/{comment_id}` — row kept, deleted_at set.
      Writes require `channels.edit`, reads `channels.view`.
- [x] Tests `test_instagram_comment_actions.py` (7 passing): rows-not-Graph
      read, tenant 404, reply stores+publishes, failed reply = failed row +
      502, hide flips row, delete sets deleted_at, no-token 403 not 500.

## Phase 3 — Comments tab (frontend) — DONE 2026-10-10

- [x] `lib/api-meta.ts`: `InstagramStoredComment` type +
      fetchInstagramComments / replyToInstagramComment / setInstagramCommentHidden /
      deleteInstagramComment; `use-inbox-realtime.ts` event union extended
      with comment / comment_updated / comment_deleted.
- [x] `components/channels/instagram/CommentsTab.tsx` (new file): threaded
      inbox (replies indented), inline reply box (Enter sends), hide/unhide,
      two-step delete, post thumbnails via the cached posts fetch, realtime
      refresh over the existing inbox WS. The old read-only placeholder in
      ListsTab.tsx is removed.
- [x] Wired into `InstagramHub.tsx` comments tab (with accountUsername);
      ESLint + `tsc --noEmit` clean. Deferred polish: hub-tab unread badge.

## Phase 4 — AI-assisted comment replies (own round, after 1-3 ship)

- Suggest-reply endpoint (LLM: comment + media caption + business profile,
  same grounding as DM autopilot); suggest-then-send, never silent
  auto-post in v1 — public replies are reputation-risky. Per-asset opt-in
  auto-reply only after suggest mode proves itself.

## Phase 5 — Meta app config (user actions, blocks live traffic)

- [ ] Add `instagram_manage_comments` + `instagram_business_content_publish`
      to the Meta app (App Review package).
- [x] Webhook fields subscribed on the Instagram object (user confirmed
      2026-10-10): comments, mentions, messages, message_edit,
      messaging_handover/postbacks/seen ON; live_comments, message_reactions,
      messaging_referral, standby, story_insights OFF (fine for now —
      consider `standby` when human handover needs a cleaner signal).
      Callback https://dev-api.sayvors.com/api/v1/meta/webhooks at v26.0.
- [ ] Staging: `alembic upgrade head` (new revision rides the 2 pending).

## Phase 7 — Publishing to the feed — DONE 2026-10-10

Images + image carousels from Sayvors to the tenant's OWN feed. Two Graph
calls: POST /{ig}/media (container from a PUBLIC https url) →
POST /{ig}/media_publish. Video/Reels are async containers (status
polling) — deliberately not in this round.

- [x] Adapter: `create_media_container` (caption / is_carousel_item),
      `create_carousel_container` (caption lives ONLY on the carousel,
      per Meta), `publish_media_container`, `get_publishing_limit`
      (read → degrades to {} like every read).
- [x] Router: `POST /instagram/{ig_id}/posts/publish` (1–10 urls → single
      or carousel; MetaAPIError → 502, no partial post to store),
      `GET /instagram/{ig_id}/publishing-limit`. Writes channels.edit,
      reads channels.view; same `_instagram_asset_or_404` tenant boundary.
- [x] Media sourcing: Sayvors storage uploads are publicly served
      (main.py mounts MEDIA_PUBLIC_PATH via StaticFiles) so upload →
      publish is one flow; non-HTTPS storage urls are refused in the UI
      with a plain-language error (Meta cannot fetch them).
- [x] Frontend: `PostComposer.tsx` in the Posts tab — uploads or pasted
      public urls, caption with 2200-char counter, quota line
      ("N of 50 posts used in the next 24h", hidden when Meta refuses the
      read), publish → grid remounts and the new post appears; it is now
      "our media" so its comments flow into the inbox automatically.
- [x] Tests `test_instagram_publish.py` (7 passing): two-call single post,
      carousel (children uncaptioned, carousel captioned, publish rides
      the carousel id), container-failure 502 without publish, publish
      failure 502, tenant 404, no-token 403, quota read + degrade.
- Deferred: video/Reels publishing (needs container status polling —
  FINISHED_STATUS — so an endpoint can't be synchronous), a publish ledger
  for exact-once retries, Stories publishing.

## Phase 6 — Instagram standalone (no Facebook Page) — after Phases 1-3

The page-linked flow (FB login → Pages → IG) breaks for businesses with a
standalone IG business account. Meta's answer: **Instagram API with
Instagram Login** (graph.instagram.com, own OAuth dialog, own tokens) —
profile, media, stories, insights, comments AND DMs, no Page involved.

- [ ] Prereq (user): create the Instagram-type app in the Meta dashboard
      (separate app id/secret) + App Review for `instagram_business_basic`,
      `instagram_business_manage_messages`, `instagram_business_manage_comments`,
      `instagram_business_content_publish`.
      UPDATE 2026-10-10: the user's dashboard now shows the "Instagram API
      with Instagram business login" use case WITH the webhook config done —
      the app side exists. Remaining: the permissions above in that use
      case's Permissions panel + the standalone OAuth flow below.
- [ ] `auth_type` column on MetaConnection (`facebook_page` |
      `instagram_direct`); InstagramAdapter base-URL switches to
      graph.instagram.com for instagram_direct connections.
- [ ] Instagram Login OAuth: authorize dialog + short→long-lived exchange +
      refresh endpoint mapping, stored on the same MetaConnection
      (provider="instagram").
- [ ] **Token refresh job — must-have**: standalone tokens live 60 days and
      silently die without refresh (page-linked page tokens mostly don't
      expire; this job only serves instagram_direct).
- [ ] `get_instagram_page_credentials()`: instagram_direct → return
      (ig_id, ig_token). One-function seam — DMs + comment replies +
      everything downstream works unchanged (verified: every send funnels
      through it).
- [ ] Webhook ingress needs nothing new — object=instagram parser handles
      both shapes; asset resolution keys on the IG user id already.
- [ ] Frontend: second connect path ("Connect Instagram" without Facebook)
      on the connect page.
- [ ] Tests: standalone OAuth exchange, token refresh, DM + comment reply
      via the direct token, page-linked regression.

## Deferred (intentionally)

- `mention.received` storage (parser emits it; needs media backfill design).
- FB Page feed comments — same table serves them; provider="facebook"
  variant of the handler when the FB hub round starts.
- Comment like_count refresh (only via posts refetch today).
