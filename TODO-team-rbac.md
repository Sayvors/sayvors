# Team RBAC fixes — progress

Audit findings being fixed, in order. (Frontend permission-aware nav deferred as agreed.)

- [x] **1. assistant.chat → ai.view** — members currently can never use AI chat (perm not in catalog)
- [x] **2. Suspension enforced platform-wide** — check member status in `get_current_user` (core/deps.py), so suspend blocks everything, not just `get_context` routes
- [x] **3. Messages endpoints** — `POST/GET /channels/{id}/messages` need `inbox.reply`/`inbox.view` + channel-level checks
- [x] **4. Reviews cluster** — list/generate/edit/regenerate/retry/reject → `reviews.view/reply`; approve → `reviews.publish` + channel-level
- [x] **5. Verification + services CRUD** — `channels.view/edit` + channel-level
- [x] **6. Meta router** — connect/disconnect/assets/profile/register need `channels.connect/remove/edit/view`
- [x] **7. Posts wiring** — create/update → `posts.create`; publish/delete → `posts.publish`
- [x] **8. Media** — upload/delete → `media.manage` (list stays `media.view`)
- [x] **9. Tests** — new RBAC enforcement tests + full suite green (998 passed; 11 pre-existing failures unchanged)
- [x] **10. Commit** — local only (no push per request)

## Round 2 — admin controls every checkbox on every role

- [x] **11. Backend**: permission editing unlocked on built-in roles (names stay fixed, delete stays blocked)
- [x] **11b. Seeding no longer re-syncs** — `ensure_system_roles` only prunes catalog-dead permissions, so admin edits stick
- [x] **12. Frontend**: Edit button on built-in roles + read-only name for them + dead billing.* checkboxes hidden
- [x] **13. Tests**: system-role permission edit passes, rename/delete still refused (32 green; full suite 1001 passed / 11 pre-existing failures)
- [x] **14. Verify + commit (local, no push)** — tsc + eslint clean

## Round 3 — no confusing "unset looks denied"

- [x] **15. Owner immunity made explicit** — `canManage` reads `is_owner` instead of relying on an empty permissions list; test proves a stripped Admin cannot lock the owner out
- [x] **16. "Follow role" state** — channel panel distinguishes "no override stored" from a stored `none` denial, shows the role's effective level, and only stores real overrides
- [x] **17. Bug: "none" was dropped on save** — `saveChannels` filtered `none` out of the payload, so a denial silently became "follow the role". Now sent verbatim; the API deletes rows only for channels left on follow
- [x] **18. Honest badge** — "Channel access · N overrides" or "· follows role"
- [x] **19. Tests + verify** — 34 green in test_team_rbac.py; full suite 1003 passed / same 11 pre-existing failures; tsc + eslint clean

## Round 4 — team page visual pass (trial, not yet global)

- [x] **20. Full channel names** — no more `truncate`; long branch names wrap, `title` keeps the full string
- [x] **21. Platform identification** — new shared `components/channels/PlatformMark.tsx` (official marks from `/public/channels`, letter tile for Google Business) + provider label + connection status dot per channel
- [x] **22. Glass** — one blur on panes only (nested blurs = grey mush), hairline + inset top highlight, cards opaque-ish, backdrop wash inside the scroll box
- [x] **23. Contrast floor** — 10px captions lifted off `text-ink/30-45` to `/50-60`; deep-violet badges got `dark:text-violet-soft` (unreadable before)
- [x] **24. Brand palette V1.0 scoped** — `.team-brand` in globals.css carries Deep Violet #3D1D6E / Magenta #B0338A / Coral #FF4F6E / Ink #14101F / Fog #F4F2F7 (dark: #6B3FB5 / #D8459F / #FF6E85). Wash runs Deep Violet → Magenta → Coral per the guideline gradient
- [x] **25. Verified visually** — compiled the project's real Tailwind output and screenshotted at 1440/390, light + dark; fixed what the renders exposed
- [ ] **26. Decision pending** — promote `.team-brand` to `:root`/`.dark` (whole dashboard) and whether to adopt the brand typeface (Inter Display / Sora; currently Geist)
