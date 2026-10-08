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
