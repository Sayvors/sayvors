# Sayvors — Production Deployment Checklist

1M-user production readiness checklist. Review every item before pointing a
production domain at the API. Items marked **[Cookie]** are G2/G1 security
controls; breaking them reintroduces the vulnerabilities we just fixed.

---

## 1. TLS / HTTPS (Mandatory)

| # | Check | Notes |
|---|-------|-------|
| T-1 | **Edge terminates HTTPS** (Caddy, ALB, Cloudflare, etc.) | API must never serve plain HTTP in production |
| T-2 | **API and frontend both on HTTPS** | Browsers refuse `Secure` cookies over HTTP |
| T-3 | **HTTP → HTTPS redirect** | Catch any plain-HTTP requests at the edge |
| T-4 | **HSTS header** (`Strict-Transport-Security: max-age=63072000; includeSubDomains; preload`) | Tells browsers to always use HTTPS |
| T-5 | **TLS 1.2+ only** | Disable TLS 1.0/1.1 at the edge |
| T-6 | **Valid cert from public CA** | Let's Encrypt, ACM, or your org's CA — no self-signed in prod |

**Config impact:** `COOKIE_SECURE=True` (your current default) — browsers only send cookies over HTTPS. Do NOT set this to `False` in production.

---

## 2. Cookie Security (G2 / G1 controls)

| # | Check | Notes |
|---|-------|-------|
| C-1 | **`COOKIE_SECURE=True`** | Cookies marked `Secure` — HTTPS only |
| C-2 | **`COOKIE_SAMESITE` correct** | `"none"` if API + frontend on **different** domains; `"lax"` if same domain |
| C-3 | **`COOKIE_DOMAIN` set** if split-domain | e.g. `.sayvors.com` so `app.sayvors.com` and `api.sayvors.com` share cookies |
| C-4 | **Access token cookie** (`ACCESS_COOKIE_NAME`) | httpOnly, Secure, 15 min TTL |
| C-5 | **Refresh token cookie** (`REFRESH_COOKIE_NAME`) | httpOnly, Secure, 7 day TTL |
| C-6 | **CSRF cookie** (`CSRF_COOKIE_NAME`) | httponly=False (JS reads it for X-CSRF-Token), Secure, SameSite=lax/none |
| C-7 | **Access token NOT in JSON body** | G2 — any endpoint returning `access_token` in JSON reintroduces XSS token theft |

**Cookie behavior:**
- Browser sends httpOnly cookies automatically with `credentials: "include"` — no JS access needed
- Frontend `apiFetch` already uses `credentials: "include"` — verify this stays intact
- WebSocket inbox reads the access token from cookies (same-origin)

---

## 3. Auth & Session Security (G1)

| # | Check | Notes |
|---|-------|-------|
| A-1 | **`JWT_SECRET` is strong and unique** | `python -c "import secrets; print(secrets.token_urlsafe(64))"` — never the default |
| A-2 | **Fail-fast on default JWT secret** | `config.py` already exits if `change-me-in-production` — keep it |
| A-3 | **Token blacklist checked in `get_current_user`** | G1 — `is_token_blacklisted()` called on every authenticated request |
| A-4 | **Token version check** | `payload.get("ver") != user.token_version` revokes on password change / logout-all |
| A-5 | **Redis fail-closed** | `AUTH_RATE_LIMIT_FAIL_CLOSED=True` — Redis down = auth denied (not bypassed) |
| A-6 | **Refresh token rotation + reuse detection** | Already implemented — reuse kills all sessions for the user |
| A-7 | **Logout blacklists access token JTI** | G1 — stolen access tokens die at logout |

---

## 4. Infrastructure (from production-later.md)

| # | Check | Notes |
|---|-------|-------|
| I-1 | **Kafka: 3-broker cluster** | Single broker = SPOF; KRaft quorum of 3 |
| I-2 | **`KAFKA_AUTO_CREATE_TOPICS_ENABLE=false`** | Prevents 1-partition topics; provision explicitly (24/12/6/6 per lane) |
| I-3 | **Redis: 6–8 GB, multi-AZ, AOF on** | Auth infrastructure — memory alarm at 75%, `noeviction` policy |
| I-4 | **Postgres read replica** | Offload analytics queries; binding constraint is connection pool |
| I-5 | **PgBouncer connection pooling** | `DATABASE_URL` → PgBouncer port 6432, `DB_POOL_MODE=transaction`, prevents connection exhaustion |
| I-6 | **DB pool right-sized** | `DB_POOL_SIZE=5`, `MAX_OVERFLOW=5` per process; boot-time headroom check |
| I-7 | **Write/read session splitting** | `get_db()` for writes (primary), `get_db_read()` for reads (replica) |
| I-8 | **S3 buckets configured** | `S3_DOCS_BUCKET` + `S3_MEDIA_BUCKET` — customer uploads never on local volume |
| I-9 | **Second box / AZ / container platform** | One OOM kill shouldn't take auth + messaging + ingestion down together |
| I-10 | **RDS PITR ≥ 7 days + restore rehearsed** | Backups tested — two migration incidents already happened |
| I-11 | **CI/CD pipeline** | GitHub Actions: lint → test → build → deploy; 82 backend tests must run before image builds |
| I-12 | **Monitoring** | Sentry (errors) + Prometheus/Grafana (metrics) scraping `/metrics` + `/readyz` |

---

## 5. Security Headers (frontend)

| # | Check | Notes |
|---|-------|-------|
| H-1 | **CSP nonce-based** (no `unsafe-inline` scripts) | G2 — XSS can't run unrestrained |
| H-2 | **`frame-ancestors 'none'`** | Clickjacking protection |
| H-3 | **`X-Content-Type-Options: nosniff`** | MIME sniffing prevention |
| H-4 | **`X-Frame-Options: DENY`** | Clickjacking |
| H-5 | **`referrer-policy: strict-origin-when-cross-origin`** | Limit referrer data |

Your `next.config.ts` already sets COOP/COEP/CSP headers — verify they're production-grade.

---

## 6. Pre-launch validation

| # | Check | How to verify |
|---|-------|---------------|
| V-1 | **Login sets httpOnly cookies** | DevTools → Application → Cookies: `access_token`, `refresh_token` both marked Secure + HttpOnly |
| V-2 | **No `access_token` in JSON response** | Login response body should NOT contain `access_token` |
| V-3 | **Cookie sent on cross-origin API call** | `apiFetch` with `credentials: "include"` — check Network tab for `Cookie` header |
| V-4 | **WebSocket connects via cookie** | Inbox WS works without `?token=` in URL |
| V-5 | **Logout clears cookies** | DevTools → cookies gone after logout |
| V-6 | **HTTP request is redirected to HTTPS** | `http://` → `https://` at the edge |
| V-7 | **Rate limiting fails closed** | Stop Redis → login should be denied (not allowed) |

---

## Quick reference: env vars for production

```
# Security
JWT_SECRET=<strong-random-64-chars>
COOKIE_SECURE=true
COOKIE_SAMESITE=none          # or "lax" if same domain
COOKIE_DOMAIN=.sayvors.com    # only if split-domain
ACCESS_COOKIE_NAME=access_token
ACCESS_COOKIE_MAX_AGE=900
REFRESH_COOKIE_NAME=refresh_token
REFRESH_COOKIE_MAX_AGE=604800
CSRF_COOKIE_NAME=csrf_token

# Auth
AUTH_RATE_LIMIT_FAIL_CLOSED=true

# Database
DATABASE_URL=postgresql+asyncpg://...?ssl=require
DATABASE_READER_URL=postgresql+asyncpg://replica-host:5432/sayvors   # optional; empty = reads hit primary
DB_POOL_MODE=transaction          # session | transaction — for PgBouncer pooling
DB_POOL_SIZE=5
DB_POOL_MAX_OVERFLOW=5
DB_POOL_TIMEOUT_SECONDS=30

# Redis (auth infrastructure)
REDIS_URL=rediss://<elasticache-endpoint>:6379/0   # rediss = TLS to Redis

# Kafka
KAFKA_BOOTSTRAP_SERVERS=<broker1:9092,broker2:9092,broker3:9092>
KAFKA_AUTO_CREATE_TOPICS_ENABLE=false

# S3
S3_DOCS_BUCKET=sayvors-docs-prod
S3_MEDIA_BUCKET=sayvors-media-prod

# Observability
GLITCHTIP_DSN=<your-sentry-dsn>
ENVIRONMENT=production
```

---

**Bottom line:** HTTPS + Secure/httpOnly cookies + G1 token revocation + G2 no-token-in-body = a production-grade auth foundation for 1M users. Everything else (Kafka HA, Redis HA, Postgres replica, S3, backups, monitoring) scales on top of it.
