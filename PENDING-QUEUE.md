# Pending Queue

Planned work that is designed but NOT yet implemented. When starting an entry, move it to "In progress" and link the branch/PR.

---

## 1. Facebook Section — Dashboard & Pages (designed 2026-09-14)

**Status:** pending (plan approved in design; implementation deferred by user request)

**Goal:** Dedicated Facebook section in the dashboard — Overview, Inbox (comments + DMs with AI-assisted replies), Automation (autoreply rules), Connect/Manage — under a new **"Facebook"** sidebar group, in a **Facebook-branded bolder look** (blue gradients `#1877f2/#00a4ef/#0f5fd6`, glassy cards) consistent with the app's light/dark system.

**Routes (new, under `apps/web/app/dashboard/facebook/`):**
- `page.tsx` — Overview (`fbOverview`)
- `inbox/page.tsx` — Inbox list (`fbInbox`, `useSearchParams` → wrap export in `<Suspense>`)
- `inbox/[conversationId]/page.tsx` — Thread (`params: Promise<...>` + `use(params)`, per `contacts/[id]/page.tsx`)
- `automation/page.tsx` — Automation (`fbAutomation`)
- `connect/page.tsx` — Connect/Manage (`fbConnect`, `<Suspense>`)

**Key implementation points:**
- `components/dashboard/Sidebar.tsx`: new group `{ label: "Facebook", items: [...] }` between "Google Business" and "Tools"; add `FacebookIcon` + `InboxIcon` inline SVGs (24x24, `stroke="currentColor"`, 1.5); reuse existing `LinkIcon`/`AutoReplyIcon`.
- `app/globals.css`: add `@theme` tokens `--color-fb-blue #1877f2`, `--color-fb-sky #00a4ef`, `--color-fb-deep #0f5fd6`, `--color-fb-bright #4d9dff`; utilities `.btn-fb` (gradient button), `.fb-glass` (backdrop-blur card), `.animate-fb-glow` (gradient border wrapper mirroring `.animate-google-glow`; add to reduced-motion block). Text always stays `text-ink dark:text-fog`; FB blue only for accents/chips/active states.
- New `components/facebook/`: `FbPageHeader`, `StatTile` (reuse `DeltaChip` from `components/analytics/StatCard.tsx`), `ActivityChart` (inline SVG per `components/analytics/Charts.tsx`; run dataviz skill palette validator), `AssetHealth`, `WebhookStatus`, `RecentActivity` (empty state today), `QuickActions`, `ConnectPanel`, `InboxList`, `InboxThread`, `FbReplyComposer`, `AutomationCard`.
- **Connect logic extraction:** new `lib/meta-connect.ts` — move from `components/channels/MetaConnections.tsx`: `Window.FB` declaration, `loadFacebookSdk()` (sdkPromise/sdkReady — recently fixed for stub-SDK readiness), `connectOAuth`, `connectWhatsApp`, plus `saveMetaAssets`/`recheckMeta`/`disconnectMetaProvider` helpers. Refactor `MetaConnections.tsx` to import (hub must stay behavior-identical). `ConnectPanel` = FB+IG-only re-skin.
- **Backend tweak:** `services/api/app/modules/channels/meta/router.py` `POST /{provider}/connect` accepts optional `{ next }` body → transaction metadata; callback already honors `transaction_metadata.get("next")` with `_SAFE_NEXT`. Frontend `lib/api-meta.ts` `startMetaConnect(provider, next?)`. Fallback: callback lands on channels hub (banner handles it); FB connect page still parses `meta_connected/meta_error/next/discovery_error` + `history.replaceState` cleanup.
- **Data strategy:**
  - *Overview (functional now):* `fetchMetaConnections()` + `fetchMetaAssets()`; `GET /api/v1/channels/?limit=100` (FB-family) + per-channel `GET /channels/{id}/autoreply` → tiles: Pages connected, Auto-replies active, Webhook freshness (`last_webhook_received_at`), designed-ahead tiles show `—`.
  - *Automation (functional now):* mirror `app/dashboard/automations/page.tsx`; `GET/PUT /api/v1/channels/{id}/autoreply` `{enabled, tone, approval_mode, databank_id, model, custom_instructions}`; tone options friendly/professional/apologetic/playful + unknown-value guard; models `GET /api/v1/llm/models`; databanks `listDatabanks()`; approval segmented control per `channels/page.tsx` pattern; triggers block disabled with "soon" pill (no backend field).
  - *Inbox (designed-ahead of backend):* new `lib/api-facebook.ts` typed contract — `fetchFbConversations` (`GET /api/v1/meta/facebook/conversations`), `fetchFbMessages` (`.../{id}/messages`), `sendFbReply` (`POST .../{id}/replies`), `generateFbReply` (`POST .../{id}/replies/generate`). Types: `FbConversation {id, kind: comment|dm, status: open|done, participants, preview, unread_count, last_message_at, external_url}`, `FbMessage {id, direction, content, status, created_at, sender_name}`. Missing endpoints → FB-branded empty card linking to connect page (no error walls). `NEXT_PUBLIC_FB_MOCK=1` returns fixtures for visual QA. Backend wiring later = implement those 4 endpoints only (inbox data model is Phase 2 in meta module; `meta_webhook_events` holds raw payloads, `channel_messages` table unwired for Meta).
- **i18n:** `lib/i18n/en.ts` + `ar.ts` in lockstep (typed `Dict`): nav keys `fbOverview/fbInbox/fbAutomation/fbConnect` (ar: نظرة عامة / صندوق الوارد / الأتمتة / الاتصال) + new top-level `facebook` string section mirrored in Arabic; use logical (`ms/me/ps/pe`) utilities for RTL.
- **Next.js 16 quirks:** all pages `"use client"`; `useSearchParams` pages wrapped in `<Suspense>`; consult `node_modules/next/dist/docs/02-pages` before writing the dynamic thread route (per `apps/web/AGENTS.md`).

**Implementation order:** (1) foundations: tokens, i18n, sidebar, page stubs → (2) connect extraction + backend `next` param → (3) overview → (4) automation → (5) inbox + mock → (6) polish (dark/light, RTL, dataviz validation).

**Verification:** `npx tsc --noEmit` + `npm run lint` in `apps/web`; backend `pytest tests/test_meta_oauth.py`; manual QA via `/run` skill (nav/active states incl. thread route, dark/light, Arabic RTL, OAuth round-trip to `/dashboard/facebook/connect`, channels hub unchanged, empty states + mock mode, reduced motion).

**Reference:** full plan at `C:\Users\it\.claude\plans\distributed-pondering-moore.md`
