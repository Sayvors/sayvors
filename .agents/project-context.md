# Sayvors Project Context

## Overview
- **Name:** Sayvors
- **Type:** 10M-user SaaS MVP monorepo
- **Branch:** `development` (default branch)
- **Python:** >=3.11, managed by `uv`
- **Backend:** FastAPI async service in `services/api/`
- **Frontend:** Next.js 16.4.3 + React 19 + Tailwind 4 in `apps/web/`
- **Workspace:** uv workspace with `services/*` members
- **Git identity:** syabahmad / syabblogger@gmail.com

## Monorepo Layout
```
apps/              web, admin, docs (docs is a placeholder)
services/api/      FastAPI backend (the only active service)
integrations/      channels (Google Business Profile publisher), payments, ai, storage, email, sms, webhooks
deployments/       empty scaffold
configs/           empty scaffold
tests/             empty
.github/           CI workflows (PR gates + staging deploy)
docs/              architecture, security, specs, tracking
```

## Backend (`services/api/`)
- **Entry:** `app/main.py`
- **Framework:** FastAPI + uvicorn + SQLAlchemy async + asyncpg + alembic
- **Auth:** JWT (PyJWT), bcrypt, refresh-token rotation, CSRF, rate-limit, account lockout
- **Cache/Queue:** Redis + aiokafka (hybrid: Docker containers + localhost:29092)
- **RAG:** pgvector, pypdfium2, python-docx, openpyxl, trafilatura, ollama, openai
- **LLM:** Gemini function-calling agent, OpenAI-compatible fallback
- **Key modules:**
  - `app/modules/auth/` — signup/login/refresh/forgot/reset/verify/rate-limit/account-lockout
  - `app/modules/rag/` — upload, parse, chunk, embed, search, jobs, live DB connectors, agentic RAG
  - `app/modules/llm/` — chat, providers (openai_compatible, gemini), TTS/STT
  - `app/modules/channels/` — Google OAuth, reviews worker, auto-reply, approval workflow
  - `app/modules/profile/` — user profile, onboarding, feedback (Redis cache + Kafka events)
  - `app/modules/analytics/` — review insights, daily metrics, performance sync
  - `app/modules/redis/` — connection manager + health router
  - `app/modules/kafka/` — producer/consumer + health router
  - `app/core/deps.py` — `get_current_user`, `get_db`
  - `app/security.py` — token encode/decode (PyJWT)
  - `app/config.py` — pydantic-settings (all keys in `.env`)
  - `app/database.py` — SQLAlchemy engine
- **Migrations:** alembic; latest `b7e4f1a9c2d8` (Localith retirement)

### Alembic chain (leaf → root)
```
b7e4f1a9c2d8  drop_localith                ← NEW
  ← f5a8c2d6e9b14375  channel_daily_rollup_version
    ← (earlier migrations)
```

## Frontend (`apps/web/`)
- **Framework:** Next.js 16.2.12, React 19.2.4, Tailwind 4.3.3, TypeScript 5
- **Structure:** all dashboard pages under `app/dashboard/*`, auth under `app/(auth)/*`
- **Dashboard redesign:**
  - Sidebar: branded avatar + popover, active-route highlight
  - Header: settings gear, help `?`, quick-create `+`, Auto Pilot pill toggle
  - Greeting: typewriter effect with Sayvors logo cursor
  - Channels: Google Business Profile connect (real OAuth), coming-soon cards
- **i18n:** English + Arabic (ar), RTL support via I18nProvider
- **Key libs:** `lib/api.ts`, `lib/api-rag.ts`, `lib/auth-context.tsx`, `middleware.ts`
- **Components:** LogoLoader (brand ring + signal arcs), AutoPilotDialog, DatabaseTab, RetrievalTab
- **Scripts:** `dev`, `build`, `start`, `lint`; no `typecheck` script, no tests

## Local Dev Commands
```bash
# API
cd services/api && uv run uvicorn app.main:app --reload --port 8000
cd services/api && uv run alembic upgrade head
cd services/api && uv run pytest -q              # 15/26 passing (pre-existing failures)

# Frontend
cd apps/web && npm run dev

# Docker (Redis + Kafka)
docker compose up -d redis kafka
# Postgres: local at localhost:5432 (user=postgres, pass=mentee, db=sayvors)

# Tests
cd services/api && uv run pytest -q               # needs uv sync --extra dev first
cd apps/web && npx tsc --noEmit --pretty           # clean
```

## Known State
- **Backend tests:** 15 failed / 26 passing (all pre-existing, not caused by our changes)
- **Frontend:** no tests, no lint CI
- **Gemini:** project 707788193034 returns 403 on generate/embed — needs billing enabled
- **Google:** `mybusinessaccountmanagement.googleapis.com` quota exhausted (429 on connect)
- **Docker:** Redis + Kafka running; Postgres stopped (using local)
