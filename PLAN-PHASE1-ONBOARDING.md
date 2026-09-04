# Phase 1: Onboarding Simplicity & Frontend Cleanup Plan

## Problem
New users land on a dashboard with 20+ pages, mock stats, and no clear first action. They don't know what to do or where to start.

---

## Part A: Onboarding Flow (`/dashboard/onboarding`)

### Backend
- Add `onboarded: bool = False` field to User model (or use localStorage flag for MVP)
- New API: `PATCH /api/v1/users/me { onboarded: true }`
- Migration to add column

### Frontend: New pages/components
- `app/dashboard/onboarding/page.tsx` — standalone onboarding flow (no sidebar), steps:
  1. **Connect Channels** — sunken cards for Instagram, Facebook Messenger, X, Google Reviews (OAuth link-out, dev/test mode buttons)
  2. **Feed the Brain** — create Databank, upload docs, explains "your AI answers from this"
  3. **Turn On Auto-Reply** — toggle per channel, pick tone, link Databank
  4. **Done** — confetti, "you're ready", redirect to dashboard
- `components/onboarding/OnboardingProgress.tsx` — step indicator (3 dots + checkmarks)
- `components/onboarding/ChannelCard.tsx` — reusable connect card with connected state
- `components/onboarding/DatabankStep.tsx` — inline create + upload widget
- `components/onboarding/AutoReplyToggle.tsx` — channel toggles + tone picker

### Flow
1. After login, `AuthGuard` (or a `dashboard/layout.tsx` check) redirects to `/dashboard/onboarding` if `!user.onboarded` (or localStorage flag)
2. Each step saves progress (localStorage) so user can refresh/resume
3. On "Done" → `PATCH onboarded=true` → redirect to `/dashboard`
4. "Skip for now" links available at each step (set onboarded=true anyway)
5. "Help ?" bubble (bottom-right) gains an onboarding checklist so users can restart

---

## Part B: Phase 1 Sidebar Trim

### Keep in sidebar (phase 1 MVP surface)
| Label | Route | Why |
|---|---|---|
| Dashboard | `/dashboard` | Home (stats + summary) |
| Databank | `/dashboard/databank` | Core: AI knowledge brain |
| Connect | `/dashboard/channels` (hub page, real) | Connect Instagram/FB/X/Google |
| Auto-Reply | `/dashboard/automations` (refactored) | Core: turn on auto-reply |

### Remove from sidebar (phase 1)
| Label | Route | Replacement |
|---|---|---|
| AI Agents group (Library, Create) | `/dashboard/agents/*` | Fold agent config into Auto-Reply setup |
| AI Tools group (STT, TTS, Chat with Docs) | `/dashboard/stt`, `/tts`, `/docs` | Placeholder pages — hide until real |
| Video Studio | `/dashboard/video-studio` | Keep code, hide from nav |
| Contacts | `/dashboard/contacts` | No backend for MVP |
| Widgets | `/dashboard/widgets` | No backend for MVP |
| Templates | `/dashboard/templates` | Placeholder — hide |
| Channels (full list in sidebar) | `/dashboard/channels/[slug]` | Only show Instagram, Facebook, X, Google Reviews in Connect hub |

### New sidebar structure
```
[Dashboard]
[Databank]
[Connect]        ← 4 channels only, badge "0/4 connected"
[Auto-Reply]     ← channel toggle + tone + Databank link
...
[Profile ▾]      ← header dropdown (already done)
```

Bottom-right "Help ?" bubble gains:
- Onboarding checklist (restart flow)
- Quick links: Connect a channel, Create a Databank, Turn on Auto-Reply

---

## Part C: Dashboard Page Rewrite

### Current: `app/dashboard/page.tsx` (502 lines)
- Full mock stats: 6 channels, 8 live activity items, 4 top leads, AI metrics, weekly chart
- Confusing for new users (all zeros for real users)

### Phase 1 replacement
- **If `!onboarded`**: Hero card "Get started in 4 steps" + CTA to `/dashboard/onboarding`
- **If onboarded but no channels connected**: "Connect your first channel" + channel cards
- **If channels connected**: Real stats (messages handled, avg response time, active channels) + recent activity feed (from `ChannelMessage` table)
- Remove: mock leads, mock weekly chart, fake health scores — replace with real data once backend supports it

---

## Part D: Placeholder Pages to Remove from Nav

All "Coming Soon" placeholder pages — keep files, remove from nav:
- `/dashboard/stt` (23 lines, placeholder)
- `/dashboard/tts` (22 lines, placeholder)
- `/dashboard/docs` (24 lines, placeholder)
- `/dashboard/templates` (24 lines, placeholder)
- `/dashboard/templates/shared` (23 lines, placeholder)
- `/dashboard/settings` (22 lines, placeholder → merge into Profile)

### Pages to redirect or hide
- `/dashboard/channels` — keep as "Connect" hub but only show 4 channels
- `/dashboard/automations` — rewrite as "Auto-Reply" config (not full automation builder)
- `/dashboard/contacts/*` — hide (no backend)
- `/dashboard/widgets` — hide (no backend)
- `/dashboard/video-studio/*` — hide (keep for later)

---

## Implementation Order

1. **Backend**: Add `onboarded` field to User + migration (small)
2. **Onboarding page**: `/dashboard/onboarding` + subcomponents (new)
3. **Sidebar trim**: Restructure `navGroups` + `bottomNav` in `Sidebar.tsx`
4. **Dashboard rewrite**: Goal-oriented empty states + real stats (conditional)
5. **Help bubble**: Add onboarding checklist to existing `HelpMenu`
6. **Clean up**: Hide placeholder pages from nav, redirect dead routes

## Files to touch
- `services/api/app/modules/users/models.py` (add `onboarded` field)
- `services/api/alembic/versions/` (new migration)
- `apps/web/app/dashboard/onboarding/page.tsx` (new)
- `apps/web/components/onboarding/*` (new, ~5 files)
- `apps/web/components/dashboard/Sidebar.tsx` (restructure nav)
- `apps/web/app/dashboard/page.tsx` (rewrite as goal-oriented)
- `apps/web/components/dashboard/Header.tsx` (Help bubble update)
- `apps/web/lib/auth-context.tsx` (expose `onboarded` in User type)
- `apps/web/components/AuthGuard.tsx` (redirect to onboarding if not onboarded)

---

*Plan written: 2026-08-13*
*Pending: User approval before implementation*
