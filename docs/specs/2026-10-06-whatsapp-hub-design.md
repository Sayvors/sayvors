# WhatsApp Hub + Channels Nav — Design Spec

Date: 2026-10-06
Status: Approved for planning
Scope: Full WhatsApp hub (profile + numbers/health + templates + settings) + sidebar IA for FB/IG scale. Multi-location brand first, SMB-friendly by default.

## 1. Aesthetic direction

**Conversational Warmth** (Soft Utility tuned for chat, not generic):
- Purpose: daily profile + health triage for 1–N locations, non-technical owners can edit without fear.
- Reference: WhatsApp chat surface + warm paper dashboard, not ops table.
- Palette: warm paper base `#F6F3EC`, white surface, ink `#16130E`, one WhatsApp green accent `#25D366` (<10% surface), amber/red only for status.
- Type: Instrument Sans (humanist, 2 weights) display + text; tabular nums for counts; never Inter display.
- Radius 12 everywhere, 2 shadows (contact + ambient), 200ms ease-out. No gradients (except avatar), no cards-in-cards.
- Memorable: live phone preview on the right that updates as you type + profile completeness ring.
- Restraint: no purple-blue gradients, no hero+3-cards, no mixed radii, no emoji-as-icons (real WhatsApp glyphs).

## 2. Information architecture — where it lives

`Channels` promoted out of Advanced drawer into MAIN (after Locations, before Databank). Expandable, 1 slot for N networks.

```
Channels ▾ [badge: unread total + red dot if any number needs fix]
  Inbox                              -> /dashboard/channels/inbox (redirect from /dashboard/inbox, unified threads, All|WhatsApp|IG|FB filter)
  ── MANAGE ──
  WhatsApp [● green/amber/gray]      -> /dashboard/channels/whatsapp?location=<id>&tab=profile
  Instagram [●]                      -> /dashboard/channels/instagram (same skeleton, different middle tab)
  Facebook [●]                       -> /dashboard/channels/facebook
  ──
  All channels health / Connect more -> /dashboard/channels (overview grid: Localith + MetaConnections + soon)
```

- Clicking `Channels` parent itself = Inbox (daily triage). Subitems = Manage (weekly config). Separated by MANAGE label + divider so jobs never confuse.
- Conditional: show only connected slugs. 0 connected -> show `Channels [START HERE]` + single child `Connect a channel`. 1 connected (e.g. WhatsApp only) -> Inbox + WhatsApp + Connect more. Unconnected never appear.
- Data: `GET /api/v1/channels?limit=100` + meta connections, cached 60s client. Loading: skeleton rows. Error: keep stale list + retry dot, never blank nav.
- Remove legacy `Automations` from sidebar (page is `redirect("/dashboard/channels")`, AI settings now inline per channel). Frees 1 slot.
- Deep links survive auth, back/refresh works via `?location=&tab=`. Tour targets updated (`nav-channels`, `nav-channels-inbox`, etc.).

Alternatives rejected: B nested-only (3 clicks deep, bad for daily edits), C inside Locations (fragments global health), B-keep-both Inbox dupes (two entries, same page = confusion).

## 3. WhatsApp hub layout — `/dashboard/channels/whatsapp`

Header (sticky): channel logo + `WhatsApp` + location switcher (dropdown, search if >5) + health pill (Connected / Re-auth needed / PIN required) + primary `Save` (enabled always, validates on click, never disabled-mystery).

Tabs (URL-synced, same order for IG/FB): `Profile | Numbers & Health | Templates | Settings`.

### Tab 1 — Profile (hero)
Two-column (stacks on mobile, preview below form):
- Left form (one column, labels above, mark optional since most required): display name (warn: Meta review on change), about (139 char counter), description (512), address, email (`type=email`), websites (list, add/remove, normalize https), vertical/category (Meta enum dropdown), profile photo (upload, crop, <5MB, preview thumb).
- Validation: on blur if touched, live re-validate after error, server errors mapped to fields, never clear form on error, draft in sessionStorage.
- Completeness ring (0–100%): missing photo/about/websites lowers score, CTA jumps to field. First-use empty: illustration + `Complete your profile` + `Copy from location` button.
- Right sticky live phone preview: WhatsApp business card mock (photo, name, verified tick, about, buttons) updates on keystroke (debounced 150ms). This is the memorable moment.

### Tab 2 — Numbers & Health
Per-number cards (per location/WABA): display number, WABA id (truncated, copy), status (active / needs_reauth -> Reconnect via Embedded Signup, unregistered -> 6-digit PIN register w/ paste allowed + resend), 24h window meter, last webhook timestamp + Refresh, test-send button. Global banner if any number broken.

### Tab 3 — Templates
List (name, lang, status, updated) + search + empty-no-results (echo query + Clear) + first-use (Create template CTA) + error-retry. Detail drawer, never modal-in-modal.

### Tab 4 — Settings
Agent assignment (existing Dropdown), Response style concise/human (existing, keep cost warning), Auto-reply + Typing + Working hours + offline message (existing Toggles), Connection card. Destructive disconnect: confirm dialog naming number + location, Undo toast 8s where possible, focus safe option.

## 4. State matrix (all tabs)

- First use (no profile yet): explain + primary action, never "No data".
- No results (templates search): echo query + Clear filters.
- Cleared/all healthy: success state ("All caught up").
- Loading first: skeleton matching layout, delayed 200ms, no flash.
- Refresh: keep old data + subtle spinner, never blank.
- Partial (one WABA fails): show loaded, mark failed card + Retry that part.
- Recoverable (timeout/5xx/offline): what happened + what to do + Retry, queue offline sends.
- Permanent (404/deleted): plain language + nearest destination.
- Permission (403): who has access + request path.
- Stale: timestamp + Refresh.
- Success: confirm + what changed (toast auto-dismiss 4s; errors persist until dismissed).

## 5. Feedback & latency

0–100ms instant (pressed state), 100ms–1s busy button (reserve space), 1–10s skeleton/determinate, 10s+ estimate + cancel. Optimistic only for toggles (revert + message on fail), never for sends/deletes. Reserve image dims to avoid shift. Touch targets ≥44px, primary actions thumb-reach, no hover-only affordances, bottom bars respect safe-area + keyboard.

## 6. Copy

Buttons name actions (`Save profile`, `Send test`, `Disconnect +1 555…`), never Submit/OK. Errors: what+why+next (`Couldn't save — connection dropped, changes kept. [Retry]`). No stack traces, no blame, sentence case, no ! in errors.

## 7. Data flow (v1, no new backend unless needed)

- Profile read/write: `GET/PATCH /{WABA_PHONE_ID}/whatsapp_business_profile` via existing `WhatsAppAdapter` + new thin proxy endpoints (or reuse `/api/v1/profile/business` if Meta-synced — plan to confirm). Photo: upload -> media id -> profile photo update.
- Numbers/health: existing `validate_connection`, `register_number`, subscribed_apps status.
- Drafts: sessionStorage per location+tab, discard on save.
- Analytics: completeness %, save success/fail, re-auth clicks.

## 8. Testing

- Unit: completeness calc, phone/URL normalize, conditional nav filter.
- Integration: profile save mapping, PIN register, template list filters.
- E2E (Playwright): 0/1/N channels nav, profile edit -> preview updates -> save -> toast, broken number -> re-auth flow, 390px + 1440px screenshots read by reviewer.
- A11y: focus-visible always, labels above inputs, correct inputmode/autocomplete, 4.5:1 body.

## 9. Rollout

1. Sidebar: remove Automations, promote Channels expandable, conditional children, Inbox redirect. 2. WhatsApp Profile tab + preview. 3. Numbers & Health. 4. Templates polish. Ship behind existing routes, no breaking URLs.
