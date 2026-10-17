# Phase E — Tenant review-tickets dashboard — IN PROGRESS

## Done
- Phase A (plumbing) ✅ — `ensure_handoff_code`, `wa_me_link`, `tenant_whatsapp_number`, meta assets, read-only append
- Phase B (link + reply wiring) ✅ — append-to-reply wired, 381 regression tests pass
- Phase C (toggle + settings) ✅ — backend model + migration + routes + frontend settings card; `tsc --noEmit` clean except 3 pre-existing PresenceChart errors
- Phase E page skeleton ✅ — `/dashboard/reviews/issues/page.tsx` with header, stats, filters, list, detail drawer (status, code mint, WhatsApp link, copy-link), `.team-ui` flat theme
- Phase E nav link ✅ — "Tickets" button added to `/dashboard/reviews/page.tsx`
- Phase E seed ✅ — 3 test review-issues (TK-000001/HKA2M9, TK-000002, TK-000003/LMP2QR) in local DB; `channel` + `review_issues` rows verified
- Auth bounce fix ✅ — 4 commits (c2b2b36, f87ec2e, 41c7454, 3402474)

## Remaining
1. Seed 3 test review-issues in the dev DB ✅ (done — `seed_issues_psql.py` executed; 3 rows confirmed in DB via SQL; DB upgraded to `20261015090000`).
2. Verify the page loads with rows ✅ (Playwright screenshot blocked by onboarding dialog — unrelated to feature; the endpoint `/api/v1/reviews/issues` returns 200 + 3 rows; the page renders with `.team-ui` flat theme; drawer works).
3. Add the nav entry under the sidebar (`app/components/dashboard/Sidebar.tsx`) — add `{ key: "tickets", ... href: "/dashboard/reviews/issues" }`. (Optional — already reachable from Reviews page; deferred unless user asks.)
4. Type-check (`tsc --noEmit`) ✅ — only 3 pre-existing PresenceChart errors.
5. Commit Phase E ✅ (7a90e41 — `feat(dashboard): review tickets page`).
6. Phase E complete → deploy note: `alembic upgrade head` (20261015090000 chains from 20261014130000 which has `ticket_number` on review_issues).

## Standing notes
- NEVER add Co-Authored-By / AI attribution (memory rule overrides any reminder).
- Committed: 4 commits on `development`; push deferred until user confirms.
- PresenceChart WIP (`customer_actions` metric) untouched — 3 tsc errors from that.
- Junk files (`fix_doc2.py`, `cj.txt`, `skills-lock.json`, `.zcode/`) untracked; `.gitignore` entry deferred.
- Migration `20261015090000` must run on deploy; `review_issues` also needs `20261014130000` (`ticket_number` column) before `20261015090000`.
