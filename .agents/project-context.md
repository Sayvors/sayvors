# Sayvors Project Context

## Overview
- **Name:** Sayvors
- **Type:** 10M-user SaaS MVP monorepo
- **Branch:** development @ 84e556d (localith integration on top)
- **Python:** >=3.11, managed by `uv`
- **Backend:** FastAPI async service in `services/api/`
- **Frontend:** Next.js 16.2.12 + React 19 + Tailwind 4 in `apps/web/`
- **Workspace:** uv workspace with `services/*` members
- **Git identity:** syabahmad / syabblogger@gmail.com

## Monorepo Layout
```
apps/              web, admin, landing, docs, mobile (mostly empty)
services/api/      FastAPI backend (the only active service)
integrations/      channels (embedsocial.py adapter), payments, ai, storage, email, sms, webhooks
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
  - `app/modules/localith/` — Localith (EmbedSocial) connect, listings, connection CRUD
  - `app/modules/analytics/` — review insights, daily metrics, performance sync
  - `app/modules/redis/` — connection manager + health router
  - `app/modules/kafka/` — producer/consumer + health router
  - `app/core/deps.py` — `get_current_user`, `get_db`
  - `app/security.py` — token encode/decode (PyJWT)
  - `app/config.py` — pydantic-settings (all keys in `.env`)
  - `app/database.py` — SQLAlchemy engine
- **Migrations:** alembic; latest `f6a7b8c9d0e1` (localith_connections)

### Alembic chain (leaf → root)
```
f6a7b8c9d0e1  localith_connections         ← NEW
  ← f5a6b7c8d9e0  databank_database_sources
    ← e4f5a6b7c8d9  profile_fields_and_feedback
      ← d9e8c7b6a5f4  response_engine
        ← c8d2f4a6b9e1  analytics
          ← b7c4d9e2f1a3  google_autoreply
            ← f3b1e7a9d0c2  onboarded
              ← ceab557d4a2e  event_outbox
                ← a1b2c3d4e5f6  user_defaults
                  ← 9528ad5dd83e  rag_auth
                    ← 8f77db8fd33e  create_all_modules (baseline)
```

## Localith Integration (current work)
- **Adapter:** `integrations/channels/embedsocial.py` — `fetch_listings()`, `fetch_items()`
- **Key:** `LOCALITH_API_KEY=es3dfbe0793d8fabac128ac458110d9e` (shared across all Sayvors users for v1)
- **Listing proved:** `Sayvors-Al Malqa` (google_id: 118011331498513777216)
- **Items:** returns `[]` (reviews not synced to Localith yet)
- **DB table:** `localith_connections` (user_id FK, listing_id, listing_name, listing_google_id, last_synced_at)
- **Router:** `app/modules/localith/router.py` — 6 endpoints:
  - `GET /api/v1/integrations/localith/config` — key presence check
  - `GET /api/v1/integrations/localith/listings` — list available listings
  - `POST /api/v1/integrations/localith/test` — probe a listing id
  - `GET /api/v1/integrations/localith/connection` — user's saved connection
  - `PUT /api/v1/integrations/localith/connection` — save/update connection
  - `DELETE /api/v1/integrations/localith/connection` — remove connection
- **UI:** `apps/web/app/dashboard/channels/page.tsx` — Localith card in channel grid, connect flow, disconnect

## Frontend (`apps/web/`)
- **Framework:** Next.js 16.2.12, React 19.2.4, Tailwind 4.3.3, TypeScript 5
- **Structure:** all dashboard pages under `app/dashboard/*`, auth under `app/(auth)/*`
- **Dashboard redesign:**
  - Sidebar: branded avatar + popover, active-route highlight
  - Header: settings gear, help `?`, quick-create `+`, Auto Pilot pill toggle
  - Greeting: typewriter effect with Sayvors logo cursor
  - Channels: Google Reviews connect (real OAuth), Localith connect (middleware), coming-soon cards
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
- **Localith reviews:** empty (`items` endpoint returns `[]`) — waiting for Localith sync
- **Docker:** Redis + Kafka running; Postgres stopped (using local)
