# Sayvors Web App

The customer-facing Next.js application. It provides sign-in and account
recovery, onboarding, and the authenticated business dashboard. Dashboard areas
include business locations and services, reviews and review issues, analytics
and benchmarks, leads, channel connections and inbox, publishing, media, posts,
notifications, team management, billing, usage, profile, and knowledge databank
tools.

## Routes

| Route | Purpose |
|-------|---------|
| `/` | Redirect to `/login` |
| `/login`, `/signup` | Account access |
| `/forgot-password`, `/reset-password` | Password recovery |
| `/verify-email`, `/verify-otp` | Account verification |
| `/onboarding` | Initial business setup |
| `/dashboard` | Dashboard overview |
| `/dashboard/analytics`, `/dashboard/benchmark`, `/dashboard/growth`, `/dashboard/insights` | Business performance and insights |
| `/dashboard/channels` and `/dashboard/channels/*` | Channel connections, inbox, and publishing |
| `/dashboard/inbox`, `/dashboard/leads`, `/dashboard/notifications` | Customer conversations and follow-up |
| `/dashboard/reviews` and `/dashboard/reviews/*` | Reviews, issues, and reply tools |
| `/dashboard/issues` | Location-level issues identified from reviews |
| `/dashboard/locations`, `/dashboard/services` | Business location and service details |
| `/dashboard/posts`, `/dashboard/posts-media`, `/dashboard/media` | Content and media management |
| `/dashboard/profile`, `/dashboard/settings`, `/dashboard/team` | Account and team settings |
| `/dashboard/billing`, `/dashboard/usage` | Plan, billing, and usage |
| `/dashboard/databank`, `/dashboard/databank/new` | Knowledge databank and creation flow |
| `/dashboard/outbox` | AI review-reply outbox: pending, posted, failed, and flagged replies |
| `/dashboard/verification` | Google location verification request tracking |
| `/dashboard/automations` | Redirects to `/dashboard/channels`; automation settings live with each connected channel |
| `/invite/{token}` | Accept a team invitation |

Nested channel and review routes include additional provider- and task-specific
screens.

## Local development

Create `apps/web/.env.local` from [`apps/web/.env.example`](.env.example), then
install dependencies and start the app:

```bash
npm run dev
```

Open `http://localhost:3000`. Set `NEXT_PUBLIC_API_URL` to the API origin
(defaults to `http://localhost:8000`). The local example also documents the
optional Google/Facebook sign-in app IDs and GlitchTip browser reporting
settings. Variables prefixed `NEXT_PUBLIC_` are exposed to browser code and
must never contain secrets.

For local HTTPS development, use `npm run dev:https`; this can help when testing
browser cookie behavior across local origins.

## Quality checks

```bash
npm run lint
npm run build
```
