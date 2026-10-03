FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps for asyncpg / cryptography / pillow-style builds, plus ffmpeg
# (converts Edge-tier mp3 voice audio to Ogg/Opus so WhatsApp renders it as a
# real voice note rather than a media file).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl ffmpeg \
 && rm -rf /var/lib/apt/lists/*

# Build context is the REPO ROOT (see deploy-staging.yml): the API imports
# integrations/channels/embedsocial.py from the repo root at runtime.
COPY services/api/pyproject.toml ./
COPY services/api/app/ ./app/
COPY services/api/alembic/ ./alembic/
COPY services/api/alembic.ini ./
COPY integrations/ ./integrations/

RUN pip install --upgrade pip && pip install -e . && pip install "uvicorn[standard]"

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
