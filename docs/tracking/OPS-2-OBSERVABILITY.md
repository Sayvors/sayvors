# OPS-2 — Observability

## Overview

Production observability stack: metrics endpoint, health checks, structured logging, request tracing, error tracking.

## What's Implemented

| Item | File | Status |
|------|------|--------|
| `/metrics` Prometheus endpoint | `app/modules/observability/` | ✅ Done |
| HEALTHCHECK on API Dockerfile | `Dockerfile` | ✅ Done |
| HEALTHCHECK on worker Dockerfile | `Dockerfile` | ✅ Done |
| Sentry error tracking | `app/observability.py` | ✅ Done |
| JSON structured logs | `app/observability.py` | ✅ Done |
| Request-ID header | `app/middleware.py` | ✅ Done |
| `/readyz` readiness probe | `app/healthcheck.py` | ✅ Done |

## Files

| File | Purpose |
|------|---------|
| `app/observability.py` | Sentry init, JSON formatter, GlitchTip integration |
| `app/healthcheck.py` | `/readyz` probe — checks DB, Redis, Kafka |
| `app/middleware.py` | Request-ID middleware, structured logging |

## Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /metrics` | Prometheus metrics (request count, latency, errors) |
| `GET /readyz` | Readiness probe — DB/Redis/Kafka connectivity |
| `GET /health` | Basic health check |

## Docker HEALTHCHECK

Both `Dockerfile.api` and `Dockerfile.worker` include:
```
HEALTHCHECK --interval=30s --timeout=15s --retries=3 \
  CMD python -m app.healthcheck
```

## Status

✅ Done — marked Fixed in `readiness-report.html`. All four observability items implemented.

## Production-Later (Deferred)

- Grafana dashboards (need Prometheus scraping `/metrics`)
- Alert rules (error rate > 5%, p99 latency > 2s)
- Distributed tracing (OpenTelemetry)
