FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Compilers and headers stay in this stage. The runtime image gets only the
# shared libraries it needs, so build-essential never ships to production.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
 && rm -rf /var/lib/apt/lists/*

# Build context is the REPO ROOT (see deploy-staging.yml): the API imports
# integrations/channels/embedsocial.py from the repo root at runtime.
COPY services/api/pyproject.toml ./
COPY services/api/app/ ./app/
RUN python -m venv /venv \
 && /venv/bin/pip install --upgrade pip \
 && /venv/bin/pip install . \
 && /venv/bin/pip install "uvicorn[standard]"

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/venv/bin:$PATH"

WORKDIR /app

# Runtime libraries only: libpq for asyncpg, curl for the healthcheck, ffmpeg
# for Edge-tier voice conversion, postgresql-client for pg_dump/pg_restore
# (admin console backups). No build-essential, no headers.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl ffmpeg postgresql-client \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --gid 10001 appuser \
 && useradd --uid 10001 --gid appuser --create-home appuser

COPY --from=builder /venv /venv
COPY services/api/alembic/ ./alembic/
COPY services/api/alembic.ini ./
COPY --chown=appuser:appuser integrations/ ./integrations/
COPY --chown=appuser:appuser services/api/app/ ./app/
# Ops/backfill scripts are part of the runtime image so a deploy can run them
# without copying files into a live container (e.g. the trial-credit backfill).
COPY --chown=appuser:appuser services/api/scripts/ ./scripts/

# Named volumes inherit this ownership on first creation. An existing volume
# may need a one-time `chown -R 10001:10001 /app/data/uploads` on the host.
RUN mkdir -p /app/data/uploads && chown -R appuser:appuser /app/data

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8000/readyz || exit 1

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
