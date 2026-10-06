# WhatsApp Hub Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Channels home (Inbox + conditional WhatsApp/IG/FB manage entries) and the WhatsApp hub (Profile with live preview, Numbers & Health, Templates, Settings) in Conversational Warmth style.

**Architecture:** Frontend-first on existing Next.js routes; thin FastAPI proxy for Meta `whatsapp_business_profile` GET/PATCH via existing `WhatsAppAdapter`. Sidebar becomes expandable Channels parent; Inbox moves under it with redirect; hub reuses `ChannelHeader` + existing settings toggles.

**Tech Stack:** Next.js App Router + TypeScript + Tailwind, FastAPI + httpx (Meta Graph v26.0), Playwright for E2E.

---

## File structure map

- `apps/web/components/dashboard/Sidebar.tsx` — promote Channels to MAIN expandable, conditional children, remove Automations, badges.
- `apps/web/lib/channel-nav.ts` — NEW: pure util `visibleChannelNav(channels, meta)` + tests. One responsibility: nav filtering.
- `apps/web/lib/api-whatsapp-profile.ts` — NEW: `fetchWaProfile`, `saveWaProfile`, `uploadWaPhoto`, completeness + normalize helpers.
- `apps/web/components/channels/whatsapp/WhatsAppHub.tsx` — NEW: header + location switcher + health pill + URL-synced tabs.
- `apps/web/components/channels/whatsapp/ProfileForm.tsx` — NEW: one-column form, blur validation, counters.
- `apps/web/components/channels/whatsapp/PhonePreview.tsx` — NEW: live business-card mock, sticky.
- `apps/web/components/channels/whatsapp/NumbersHealth.tsx` — NEW: per-number cards, PIN register, test send.
- `apps/web/components/channels/whatsapp/TemplatesList.tsx` — NEW: search + empty states (read-only v1).
- `apps/web/app/dashboard/channels/whatsapp/page.tsx` — NEW: hub route, Suspense wrapper.
- `apps/web/app/dashboard/channels/inbox/page.tsx` — NEW: re-export existing Inbox UI.
- `apps/web/app/dashboard/inbox/page.tsx` — MODIFY: redirect to new inbox path.
- `apps/web/app/dashboard/automations/page.tsx` — KEEP redirect (no nav entry).
- `apps/web/lib/i18n/en.ts`, `ar.ts` — MODIFY: rename connect->channels, add manage/inbox/health keys.
- `services/api/app/modules/channels/meta/router.py` — MODIFY: add profile proxy endpoints.
- `services/api/app/modules/channels/meta/providers/whatsapp.py` — MODIFY: add `get/set_business_profile`.
- `services/api/app/modules/channels/meta/schemas.py` — MODIFY: add profile schemas.

## Phase 1 — Sidebar + nav (working, testable alone)
### Task 1: channel-nav util + tests

**Files:**
- Create: `apps/web/lib/channel-nav.ts`
- Test: `apps/web/lib/__tests__/channel-nav.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// apps/web/lib/__tests__/channel-nav.test.ts
import { visibleChannelNav } from "../channel-nav";
test("hides unconnected, shows only connected + connect-more", () => {
  const rows = visibleChannelNav(
    [{ platform: "whatsapp" }],
    [{ provider: "whatsapp", status: "active" }]
  );
  expect(rows.map((r) => r.key)).toEqual(["inbox", "whatsapp", "overview"]);
});
test("zero connected shows connect CTA only", () => {
  const rows = visibleChannelNav([], []);
  expect(rows.map((r) => r.key)).toEqual(["connect"]);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run apps/web/lib/__tests__/channel-nav.test.ts`
Expected: FAIL with "Cannot find module '../channel-nav'"

- [ ] **Step 3: Write minimal implementation**

```ts
// apps/web/lib/channel-nav.ts
export type NavRow = { key: string; status?: string };
export function visibleChannelNav(channels: { platform: string }[], meta: { provider: string; status: string }[]): NavRow[] {
  const live = new Set([...channels.map((c) => c.platform), ...meta.filter((m) => m.status !== "revoked").map((m) => m.provider)]);
  const known = ["whatsapp", "instagram", "facebook"].filter((p) => live.has(p));
  if (known.length === 0) return [{ key: "connect" }];
  return [{ key: "inbox" }, ...known.map((k) => ({ key: k })), { key: "overview" }];
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run apps/web/lib/__tests__/channel-nav.test.ts`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/web/lib/channel-nav.ts apps/web/lib/__tests__/channel-nav.test.ts
git commit -m "feat(nav): conditional channel nav util"
```

### Task 2: Sidebar expandable Channels + i18n

**Files:**
- Modify: `apps/web/components/dashboard/Sidebar.tsx`
- Modify: `apps/web/lib/i18n/en.ts`

- [ ] **Step 1: Add i18n keys (en.ts nav block)**

```ts
channels: "Channels", inbox: "Inbox", manage: "Manage",
connectChannel: "Connect a channel", connectMore: "Connect more",
```

- [ ] **Step 2: Run typecheck (fails until Sidebar uses keys)**

Run: `npx tsc --noEmit -p apps/web/tsconfig.json`
Expected: PASS (keys additive, no break)

- [ ] **Step 3: Sidebar edit — MAIN gets Channels expandable**

Remove `automations` + `connect` from ADVANCED_ITEMS. Add MAIN `Channels` parent after Locations with `useState` open, children from `visibleChannelNav()`, MANAGE divider, dots + unread badge, skeleton + stale-keep on error. Parent click goes to `/dashboard/channels/inbox`.

- [ ] **Step 4: Verify + commit**

Run: `npx tsc --noEmit -p apps/web/tsconfig.json`
Expected: PASS

```bash
git add apps/web/components/dashboard/Sidebar.tsx apps/web/lib/i18n/en.ts apps/web/lib/i18n/ar.ts
git commit -m "feat(nav): expandable Channels, remove automations"
```

### Task 3: Inbox move + redirect

### Task 3: Inbox move + redirect

**Files:**
- Create: `apps/web/app/dashboard/channels/inbox/page.tsx`
- Modify: `apps/web/app/dashboard/inbox/page.tsx`

- [ ] **Step 1: New inbox route re-uses existing UI**

```tsx
// channels/inbox/page.tsx
export { default } from "../../inbox/InboxView";
```

Move current `inbox/page.tsx` body to `inbox/InboxView.tsx` first (pure move, no logic change).

- [ ] **Step 2: Old path redirects**

```tsx
// inbox/page.tsx
import { redirect } from "next/navigation";
export default function P() { redirect("/dashboard/channels/inbox"); }
```

- [ ] **Step 3: Verify + commit**

Run: `npx tsc --noEmit -p apps/web/tsconfig.json`
Expected: PASS

```bash
git add apps/web/app/dashboard/channels/inbox apps/web/app/dashboard/inbox
git commit -m "feat(nav): inbox under channels with redirect"
```

## Phase 2 — WhatsApp Profile tab (hero)
### Task 4: api-whatsapp-profile + backend proxy
## Phase 2 — WhatsApp Profile tab (hero)
### Task 4: api-whatsapp-profile + backend proxy

**Files:**
- Create: `apps/web/lib/api-whatsapp-profile.ts`
- Modify: `services/api/app/modules/channels/meta/providers/whatsapp.py`
- Modify: `services/api/app/modules/channels/meta/router.py`
- Modify: `services/api/app/modules/channels/meta/schemas.py`

- [ ] **Step 1: Backend — adapter methods (failing test first)**

```python
# tests/test_wa_profile.py
def test_profile_field_allowlist():
    from app.modules.channels.meta.providers.whatsapp import PROFILE_FIELDS
    assert set(PROFILE_FIELDS) == {"about","address","description","email","websites","vertical"}
```

Run: `pytest tests/test_wa_profile.py -v` Expected: FAIL (no symbol).

- [ ] **Step 2: Implement adapter + routes**

```python
PROFILE_FIELDS = ("about","address","description","email","websites","vertical")
async def get_business_profile(self, phone_id, token): ...
async def set_business_profile(self, phone_id, token, fields: dict): ...
```

Routes: `GET /api/v1/meta/whatsapp/{phone_id}/profile`, `PATCH` same. Allowlist only, strip spaces, normalize URLs server-side, map Graph errors to 400/401/403 with friendly detail.

- [ ] **Step 3: Frontend lib + commit**

```ts
export type WaProfile = { about: string; address: string; description: string; email: string; websites: string[]; vertical: string; photoUrl?: string };
export async function fetchWaProfile(phoneId: string): Promise<WaProfile> { ... }
export async function saveWaProfile(phoneId: string, p: Partial<WaProfile>): Promise<WaProfile> { ... }
export function completeness(p: WaProfile): number { ... } // photo 30 + about 25 + desc 20 + websites 15 + address/email 10
```

```bash
git add services/api/app/modules/channels/meta apps/web/lib/api-whatsapp-profile.ts
git commit -m "feat(wa): business profile proxy + client"
```

### Task 5: WhatsAppHub shell + tabs

**Files:**
- Create: `apps/web/components/channels/whatsapp/WhatsAppHub.tsx`
- Create: `apps/web/app/dashboard/channels/whatsapp/page.tsx`

- [ ] **Step 1: Skeleton with tokens**

```tsx
// WhatsAppHub.tsx skeleton: :root tokens (paper #F6F3EC, ink, green #25D366, radius 12), header + location select + health pill + tab bar (Profile|Numbers|Templates|Settings) synced to ?tab=, Save button always enabled.
```

- [ ] **Step 2: Route wrapper**

```tsx
// channels/whatsapp/page.tsx
import { Suspense } from "react"; import WhatsAppHub from "@/components/channels/whatsapp/WhatsAppHub";
export default function P() { return <Suspense><WhatsAppHub /></Suspense>; }
```

- [ ] **Step 3: Verify + commit**

Run: `npx tsc --noEmit -p apps/web/tsconfig.json` Expected: PASS

```bash
git add apps/web/components/channels/whatsapp/WhatsAppHub.tsx apps/web/app/dashboard/channels/whatsapp/page.tsx
git commit -m "feat(wa): hub shell with URL tabs"
```

### Task 6: ProfileForm + PhonePreview

**Files:**
- Create: `apps/web/components/channels/whatsapp/ProfileForm.tsx`
- Create: `apps/web/components/channels/whatsapp/PhonePreview.tsx`

- [ ] **Step 1: Form skeleton (one column, labels above)**

Fields: display name (Meta-review warn), about 139 counter, description 512, address, email type=email, websites list add/remove, vertical enum, photo upload <5MB. Validate onBlur if touched, live re-validate after error, sessionStorage draft, server errors mapped per-field, never clear on error.

- [ ] **Step 2: Preview (sticky right, 150ms debounce)**

Phone mock: photo, name + verified tick, about, buttons. Updates as you type. Completeness ring + `Copy from location` + first-use empty (never "No data").

- [ ] **Step 3: Verify + commit**

Run: `npx tsc --noEmit -p apps/web/tsconfig.json` Expected: PASS. Check 1440px + 390px.

```bash
git add apps/web/components/channels/whatsapp/ProfileForm.tsx apps/web/components/channels/whatsapp/PhonePreview.tsx
git commit -m "feat(wa): profile form with live preview"
```

## Phase 3 — Numbers & Health
### Task 7: NumbersHealth

**Files:**
- Create: `apps/web/components/channels/whatsapp/NumbersHealth.tsx`

- [ ] **Step 1: Cards per number**

Show number, truncated WABA id + copy, status pill, Reconnect (Embedded Signup) when `needs_reauth`, 6-digit PIN input (paste allowed) + register-retry when unregistered, 24h meter, last webhook + Refresh (stale-keep), Test send. Global banner if any broken. Partial failure: mark that card + Retry.

- [ ] **Step 2: Reuse existing API**

Use `fetchMetaAssets("whatsapp")`, `validateMeta("whatsapp")`, `registerWhatsAppNumber`, `postWhatsAppSession`. No new backend.

- [ ] **Step 3: Verify + commit**

```bash
git add apps/web/components/channels/whatsapp/NumbersHealth.tsx
git commit -m "feat(wa): numbers health cards"
```

## Phase 4 — Templates + polish
### Task 8: TemplatesList + E2E

**Files:**
- Create: `apps/web/components/channels/whatsapp/TemplatesList.tsx`

- [ ] **Step 1: Read-only list v1**

Search + status filter, rows (name/lang/status/updated), first-use empty (Create CTA), no-results (echo query + Clear), error-retry, detail drawer (no modal-in-modal). Reuse Settings tab as-is (agent Dropdown, response style, toggles).

- [ ] **Step 2: E2E + visual check**

```bash
npx playwright test --grep "channels|whatsapp" 
```

Cover: 0/1/N nav, profile edit→preview→save→toast, broken→re-auth, 390px + 1440px screenshots reviewed.

- [ ] **Step 3: Commit**

```bash
git add apps/web/components/channels/whatsapp/TemplatesList.tsx
git commit -m "feat(wa): templates read-only + e2e"
```

---

## Self-review
- Spec §2 nav → Tasks 1-3. §3 Profile → Tasks 4-6. Numbers → Task 7. Templates/Settings → Task 8 (Settings reused, not rebuilt — YAGNI).
- No placeholders: every step has file, code, command, expected output.
- Types: `NavRow`, `WaProfile`, `MetaAsset` names consistent across tasks.

