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

## Round 5 — claymorphism replaces the glass trial

The glass pass was the wrong read of the brief: "claymorphism" was asked for and
glassmorphism shipped. Glass is now gone from the page entirely.

- [x] **27. Clay tokens** — `.team-clay` in globals.css: pastel surfaces (#f3e8ff / #ffe8d9 / #d9f2e6, never white), 32/24/20 radius, text #3b2d5e (10.3:1 on lavender), the 35/68 + 8/16 shadow stack on interactive elements, tighter 12/24 + 4/8 on buttons and inputs
- [x] **28. Press feedback** — `translateY(2px) scale(0.98)`; `box-shadow` is never animated
- [x] **29. Destructive buttons recessed** — no outer shadow, insets only, so Remove is legible on a peach card instead of vanishing into it
- [x] **30. Focus kept** — 3px solid `:focus-visible` outline, with `:focus:not(:focus-visible)` suppressed rather than `outline-none`; every `outline-none` removed
- [x] **31. Containers outer-only** — panels and cards get the outer shadow and no insets
- [x] **32. House rules written down** — `apps/web/AGENTS.md`: never gradients, never glassmorphism, single top-left light source, 3px focus ring, brand palette
- [x] **33. Verified** — no gradients / no blur / no 2px radius remain in the page; rendered at 1440 and 390, light and dark; tsc + eslint clean

## Round 6 — clay removed, flat three-colour system, audit fixes

- [x] **34. Claymorphism deleted** — every `--clay-*` token, `.clay-*` class and
      clay reference is gone from the page and globals.css
- [x] **35. Locked palette in code** — `#000000` ink, `#FFFFFF` surfaces, `#F5F5F5`
      page; hairlines and secondary text are black at low alpha, so no fourth hue
- [x] **36. Critical: dark-mode buttons were invisible** — `--ui-surface` used as a
      foreground gave white-on-white (1.00:1). Added `--ui-on-ink` (white light /
      black dark)
- [x] **37. Critical: 390px horizontal overflow** — `scrollWidth` 464 → 390. Cards
      needed `min-w-0` (grid items take the widest `<option>` as their minimum)
      and the bulk "All …" rows needed `flex-wrap`
- [x] **38. Critical: status tiers failed AA** — 7 serious axe nodes at 2.96–3.31:1,
      plus violet/emerald/amber/red. Status is now carried by weight and ink
- [x] **39. Cascade bug** — unlayered `.ui-input` beat Tailwind utilities, so the
      "Follow role" grey never rendered and the no-access/edit branches were
      byte-identical
- [x] **40. Layout** — `self-start` removed and the open card spans two columns
      (an ~841px² hole beside a 989px card); the three-deep white nesting is now
      panel → card → sunken block; channel rows carry a hairline
- [x] **41. Type floor** — the 10px tier is deleted (18 sites → 12px)
- [x] **42. Touch targets** — 52 under 44px → 0
- [x] **43. Error recovery** — a failed load rendered as "No members yet."; it now
      says what failed and offers Try again
- [x] **44. Smaller items** — `.ui-chip` primitive so badges stop wearing input
      chrome, `StatusDot` states spelled out for screen readers, dead violet hovers
      deleted, spinner covered by `prefers-reduced-motion`, `PlatformMark` tile on
      `--ui-*` tokens
- [x] **45. Verified** — axe-core **0 violations light and dark**; no overflow at
      1440 or 390; 0 box-shadow values on the page; 0 targets under 44px; 0 console
      errors; tsc + eslint clean
