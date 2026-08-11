# Sayvors Project Context

## Overview
- **Name:** Sayvors
- **Type:** 10M-user SaaS MVP monorepo
- **Branch:** development @ e58b59a
- **Python:** >=3.11, managed by `uv`
- **Backend:** FastAPI async service in `services/api/`
- **Frontend:** Next.js 16.2.12 + React 19 + Tailwind 4 in `apps/web/`
- **Workspace:** uv workspace with `services/*` members

## Monorepo Layout
```
apps/              web, admin, landing, docs, mobile (mostly empty)
services/api/      FastAPI backend (the only active service)
integrations/      channels, payments, ai, storage, email, sms, webhooks (scaffolds)
infrastructure/    empty scaffold
deployments/       empty scaffold
configs/           empty scaffold
tests/             empty
.github/           empty (no CI)
docs/              empty
```

## Backend (`services/api/`)
- **Entry:** `app/main.py`
- **Framework:** FastAPI + uvicorn + SQLAlchemy async + asyncpg + alembic
- **Auth:** JWT (PyJWT), bcrypt, refresh-token rotation
- **Cache/Queue:** Redis + aiokafka
- **RAG:** pgvector, pypdfium2, python-docx, openpyxl, trafilatura, ollama, openai
- **Key modules:**
  - `app/modules/auth/` — signup/login/refresh/forgot/reset/verify/rate-limit
  - `app/modules/rag/` — upload, parse, chunk, embed, search, jobs
  - `app/modules/llm/` — chat, providers (openai_compatible, gemini), TTS/STT
  - `app/modules/channels/` — platform webhooks + OAuth tokens
  - `app/modules/users/` — legacy user routes (unregistered)
  - `app/core/deps.py` — `get_current_user`
  - `app/security.py` — token encode/decode
  - `app/config.py` — pydantic-settings, hardcoded JWT secret default
  - `app/database.py` — SQLAlchemy engine with default pool
- **Migrations:** alembic; 1 pending migration (rag + auth tables applied)

## Frontend (`apps/web/`)
- **Framework:** Next.js 16.2.12, React 19.2.4, Tailwind 4.3.3, TypeScript 5
- **Structure:** all dashboard pages under `app/dashboard/*`, auth under `app/(auth)/*`
- **Important pages:**
  - `app/dashboard/page.tsx` — KPIs (mock data)
  - `app/dashboard/databank/page.tsx` — RAG uploads
  - `app/dashboard/agents/*` — agent creation/customization (dead buttons)
  - `app/dashboard/automations/*` — wizard (dead buttons)
  - `app/dashboard/channels/[slug]/page.tsx` — OAuth stubs
  - `app/dashboard/widgets/page.tsx` — local state only
  - `app/dashboard/contacts/*`, `conversations/*` — hardcoded mock data
- **Key libs:** `lib/api.ts`, `lib/api-rag.ts`, `lib/auth-context.tsx`, `middleware.ts`
- **Scripts:** `dev`, `build`, `start`, `lint` only; no `typecheck`, no tests
- **AGENTS.md note:** Next.js 16 has breaking changes; read `node_modules/next/dist/docs/` if editing.

## Known Critical Issues (from FIXES-NEEDED.md)
1. **Auth token confusion:** any JWT type passes as access token (`deps.py:26`).
2. **Reset token leaked:** `forgot_password` returns signed reset token in response (`auth/router.py:205`).
3. **Default JWT secret:** `change-me-in-production` in `config.py:6`.
4. **DB password committed:** `mentee` in `alembic.ini`, `.env.example`.
5. **RAG upload broken:** files read into memory but never persisted; parser expects `/tmp/sayvors_docs/{id}.{type}` (`rag/service.py:87-108`).
6. **Unbounded upload:** `file.read()` with no size cap.
7. **No deployment path:** no Dockerfiles, empty `docker-compose.yml`, no CI, no backups, no monitoring.
8. **Frontend CSP broken:** unclosed quote, hardcoded `localhost:8000`, `unsafe-eval` in prod (`middleware.ts`).
9. **Frontend auth split:** localStorage tokens dead vs cookie auth; `AuthGuard` checks localStorage.
10. **Dashboard unprotected:** no route protection; `AuthGuard` unused.

## Tooling
- `Makefile` only has `api-dev`, `api-migrate`, `api-new-module`.
- `docker-compose.yml` is `services: {}`.
- No tests, no lint/typecheck config for Python, no CI/CD.

## Local Dev Commands
```bash
# API
cd services/api && uv run uvicorn app.main:app --reload --port 8000
cd services/api && uv run alembic upgrade head

# Frontend
cd apps/web && npm run dev
```

## Open Questions (from audit)
1. Deploy platform (Azure recommended given existing skills).
2. Install pgvector now? Recommended: yes.
3. Scope next pass? Recommended: backend criticals (A+B), then C+D.
4. File storage for RAG? Recommended: local disk now, abstract for S3/Blob later.
5. Email sending? Recommended: real SMTP (SendGrid/SES).
