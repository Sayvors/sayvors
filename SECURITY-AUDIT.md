# 🔒 Security Audit Report — Sayvors / Freebuff

**Date:** August 13, 2026
**Auditor:** Buffy (AI Security Analysis)
**Scope:** Full-stack application — FastAPI backend (`services/api`) + Next.js frontend (`apps/web`)
**Framework Versions:** FastAPI ≥0.115, Next.js (App Router), SQLAlchemy 2.0+, PyJWT ≥2.10, bcrypt ≥4.2

---

## 📋 Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [OWASP Top 10 Compliance](#2-owasp-top-10-compliance)
3. [Authentication & Authorization](#3-authentication--authorization)
4. [Cryptography & Secrets Management](#4-cryptography--secrets-management)
5. [Session Management](#5-session-management)
6. [Input Validation & Injection Prevention](#6-input-validation--injection-prevention)
7. [Cross-Site Scripting (XSS)](#7-cross-site-scripting-xss)
8. [Cross-Site Request Forgery (CSRF)](#8-cross-site-request-forgery-csrf)
9. [API Security](#9-api-security)
10. [Frontend Security](#10-frontend-security)
11. [Infrastructure & Deployment](#11-infrastructure--deployment)
12. [Data Protection & Privacy](#12-data-protection--privacy)
13. [Error Handling & Logging](#13-error-handling--logging)
14. [File Upload & Document Processing](#14-file-upload--document-processing)
15. [Webhook Security](#15-webhook-security)
16. [Dependencies & Supply Chain](#16-dependencies--supply-chain)
17. [Detailed Findings](#17-detailed-findings)
18. [Remediation Roadmap](#18-remediation-roadmap)

---

## 1. Executive Summary

### Overall Security Rating: **B+ (Good)**

The Sayvors application demonstrates a **solid security foundation** with proper implementation of industry-standard patterns including JWT authentication, CSRF protection, rate limiting, password hashing, and comprehensive security headers. The codebase follows security-conscious design principles with token rotation, account lockout, and encrypted OAuth token storage.

### Key Strengths
- ✅ bcrypt with 12 rounds for password hashing
- ✅ JWT access + refresh token architecture with rotation
- ✅ Double-submit CSRF protection
- ✅ Multi-layer rate limiting (API + frontend)
- ✅ Comprehensive security headers (CSP, HSTS, X-Frame-Options)
- ✅ OAuth token encryption at rest (Fernet)
- ✅ SQL injection prevention via SQLAlchemy ORM
- ✅ TrustedHost middleware
- ✅ Webhook signature verification
- ✅ Account lockout after failed attempts

### Critical Issues Found: 2 *(originally 3 — C-01 reclassified: `.env` is git-ignored)*
### Medium Issues Found: 9
### Low Issues Found: 6
### Informational: 4

> **Reconciliation note (2026-08-13):** Several `FIXES-NEEDED.md` CRITICALs (A1 token-type, A2 token leakage, A14 TrustedHost, B24 webhook HMAC) are **already remediated in code** and marked resolved in `FIXES-NEEDED.md`. Remaining verified gaps are **G1–G9** (see Detailed Findings §17.5). The B+ rating stands for the *foundation* but assumes the G1/G2 HIGH gaps are closed before launch.

---

## 2. OWASP Top 10 Compliance

| OWASP Category | Status | Notes |
|---|---|---|
| **A01: Broken Access Control** | ⚠️ Partial | User-scoped queries enforced; blacklist function exists but NOT checked in `get_current_user` (C-02 / G1) |
| **A02: Security Misconfiguration** | ✅ Good | CORS, CSP, HSTS configured; some dev defaults carry risk |
| **A03: Software Supply Chain** | ⚠️ No audit | No `npm audit` / `pip-audit` in CI |
| **A04: Cryptographic Failures** | ⚠️ Partial | Default JWT secret is weak, but `.env` is **git-ignored** and app **fails fast at startup** if the default is unchanged (`config.py:50-53`) |
| **A05: Injection** | ✅ Good | SQLAlchemy ORM prevents SQL injection; input validation via Pydantic |
| **A06: Vulnerable Components** | ⚠️ Unknown | No automated dependency scanning detected |
| **A07: Authentication Failures** | ✅ Good | Rate limiting, account lockout, password hashing all present |
| **A08: Software & Data Integrity** | ⚠️ Partial | Outbox pattern for events; no CI/CD integrity verification |
| **A09: Security Logging & Monitoring** | ✅ Good | Auth events logged via outbox pattern; structured logging |
| **A10: Server-Side Request Forgery** | ✅ Good | External URLs validated; no open redirect patterns |

---

## 3. Authentication & Authorization

### 3.1 Password Security

**File:** `services/api/app/security.py`

| Check | Status | Detail |
|---|---|---|
| Hashing algorithm | ✅ bcrypt | `bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12))` |
| Work factor | ✅ 12 rounds | Industry standard (10-12 recommended) |
| Password minimum length | ✅ 8 chars | Enforced via Pydantic `Field(min_length=8)` |
| Password complexity | ❌ Missing | No uppercase/lowercase/number/special char requirement |
| Password stored in plaintext | ✅ Never | Only `password_hash` column in DB |
| Timing-safe comparison | ✅ bcrypt | `bcrypt.checkpw()` uses constant-time comparison |

### 3.2 JWT Token Security

**File:** `services/api/app/security.py`

| Check | Status | Detail |
|---|---|---|
| Access token expiry | ✅ 15 minutes | `JWT_ACCESS_EXPIRATION_MINUTES: 15` |
| Refresh token expiry | ✅ 7 days | `JWT_REFRESH_EXPIRATION_DAYS: 7` |
| Token type enforcement | ✅ Yes | `type` field validated (`access` vs `refresh`) |
| Unique JTI per token | ✅ Yes | `secrets.token_hex(16)` for each token |
| Algorithm specified | ✅ HS256 | Explicit algorithm, not `none` |
| Secret key strength | ⚠️ Configurable | Default `"change-me-in-production"` — but app **fails fast at startup** if unchanged (`config.py:50-53`) |
| Token blacklisting | ⚠️ Partial | Redis blacklist exists but NOT checked in `get_current_user` |

### 3.3 Account Lockout

**File:** `services/api/app/modules/auth/service.py`

| Check | Status | Detail |
|---|---|---|
| Lockout enabled | ✅ Yes | After `MAX_LOGIN_ATTEMPTS` (5) failed attempts |
| Lockout duration | ✅ 15 minutes | `LOCKOUT_MINUTES: 15` |
| Counter reset on success | ✅ Yes | `user.failed_login_attempts = 0` on successful login |
| Lockout check before auth | ✅ Yes | `if user.locked_until > now: raise ValueError` |

### 3.4 ⚠️ CRITICAL: Missing Token Blacklisting in `get_current_user`

**File:** `services/api/app/core/deps.py`

```python
# CURRENT CODE — does NOT check blacklist
async def get_current_user(...):
    payload = jwt.decode(token, settings.JWT_SECRET, ...)
    # Missing: if await is_token_blacklisted(payload.get("jti")): raise 401
```

**Impact:** Revoked tokens (via logout or password reset) remain valid until they expire naturally.

---

## 4. Cryptography & Secrets Management

### 4.1 Secret Storage

| Check | Status | Detail |
|---|---|---|
| Secrets in environment variables | ✅ Yes | `pydantic-settings` loads from `.env` |
| `.env` in `.gitignore` | ✅ Yes | `.env` and `.env.*` excluded |
| `.env` file tracked in git | ✅ No | Verified git-ignored (`git check-ignore services/api/.env`) — not in repo |
| Secret rotation mechanism | ❌ Missing | No documented rotation procedure |
| Separate secrets per environment | ⚠️ Partial | Single `.env` file, no staging/prod separation |

### 4.2 ⚠️ RECLASSIFIED: JWT Secret Not in Git (verified 2026-08-13)

**Original claim (C-01):** "`services/api/.env` tracked by git, contains live JWT_SECRET."

**Verified reality:** `.env` is **git-ignored** (confirmed via `git check-ignore services/api/.env`). No `.env` file is tracked. The previously-cited secret string is **not present in the repository**.

**Residual risk:**
- The default `JWT_SECRET="change-me-in-production"` is still hardcoded in `config.py:6`, but the app now **fails fast at startup** if unchanged (`config.py:50-53`). As long as a real secret is supplied via `.env`/env in every environment, this is not exploitable.
- `alembic.ini:4` still hardcodes a dev DB password (`postgres:mentee@…`) — tracked in git (see G6 / `FIXES-NEEDED` A4). Low real risk (localhost dev) but should be rotated and scrubbed from history.

**Remediation:**
1. Supply a strong `JWT_SECRET` via `.env` in all environments (already required by fail-fast).
2. Scrub `mentee` from `alembic.ini` + git history; use an env-injected DB URL.

### 4.3 OAuth Token Encryption

**File:** `services/api/app/modules/channels/service.py`

| Check | Status | Detail |
|---|---|---|
| Tokens encrypted at rest | ✅ Yes | Fernet symmetric encryption |
| Key derivation | ⚠️ Derived from JWT_SECRET | `sha256(JWT_SECRET)` — single key for all encryption |
| Key rotation | ❌ Not supported | Changing JWT_SECRET breaks decryption of existing tokens |

### 4.4 Token Hashing

**File:** `services/api/app/security.py`

| Check | Status | Detail |
|---|---|---|
| Refresh tokens hashed before storage | ✅ Yes | SHA-256 hash stored in DB |
| Verification tokens hashed | ✅ Yes | Email verification + password reset tokens hashed |
| Timing-safe hash comparison | ✅ SHA-256 | Hashes compared via SQLAlchemy query |

---

## 5. Session Management

### 5.1 Refresh Token Handling

**File:** `services/api/app/modules/auth/service.py`

| Check | Status | Detail |
|---|---|---|
| Token rotation on refresh | ✅ Yes | Old token revoked, new token issued |
| Old token blacklisted in Redis | ✅ Yes | `blacklist_token(jti, ttl)` called |
| Fingerprint binding | ✅ Yes | `create_token_fingerprint(user_agent, ip)` |
| Session stored in Redis | ✅ Yes | `store_session(user_id, session_id, data, ttl)` |
| Logout invalidates tokens | ✅ Yes | Deletes from DB + Redis |
| Logout all devices | ✅ Yes | `delete_all_sessions(user_id)` |
| Password reset invalidates all sessions | ✅ Yes | All refresh tokens deleted |

### 5.2 Cookie Security

**File:** `services/api/app/modules/auth/router.py`

| Check | Status | Detail |
|---|---|---|
| Refresh token cookie: `httponly` | ✅ Yes | `httponly=True` |
| Refresh token cookie: `secure` | ✅ Yes | `secure=True` |
| Refresh token cookie: `samesite` | ✅ Yes | `samesite="lax"` |
| CSRF cookie: `httponly` | ✅ Correct | `httponly=False` (readable by JS for double-submit) |
| CSRF cookie: `secure` | ✅ Yes | `secure=True` |
| Cookie path | ✅ Yes | `path="/"` |

### 5.3 Token Cleanup

| Check | Status | Detail |
|---|---|---|
| Expired tokens cleaned on startup | ✅ Yes | `cleanup_expired_data()` deletes old records |
| Login attempts retained | ⚠️ 30 days | Old login attempts cleaned after 30 days |
| Refresh token retention | ✅ 7 days | Expired/revoked tokens cleaned after 7 days |

---

## 6. Input Validation & Injection Prevention

### 6.1 SQL Injection

| Check | Status | Detail |
|---|---|---|
| ORM usage | ✅ SQLAlchemy | All queries use parameterized ORM methods |
| Raw SQL usage | ⚠️ Limited | `rag/search.py` uses `text()` with bind parameters |
| String concatenation in queries | ✅ None found | No `f"SELECT...{user_input}"` patterns detected |

**Verified safe patterns:**
```python
# services/api/app/modules/auth/service.py
result = await db.execute(select(User).where(User.email == body.email))

# services/api/app/modules/rag/search.py (parameterized)
result = await db.execute(load_sql, {"databank_id": databank_id})
```

### 6.2 Command Injection

| Check | Status | Detail |
|---|---|---|
| `os.system()` calls | ✅ None found | No shell command execution detected |
| `subprocess` usage | ✅ None found | No subprocess calls detected |
| `eval()` / `exec()` | ✅ None found | No dynamic code execution detected |

### 6.3 Pydantic Validation

**File:** `services/api/app/modules/auth/schemas.py`

| Check | Status | Detail |
|---|---|---|
| All inputs validated via Pydantic | ✅ Yes | `SignupRequest`, `LoginRequest`, etc. |
| Field constraints enforced | ✅ Yes | `min_length=8` on passwords |
| Type coercion | ✅ Yes | Pydantic strict type checking |
| Unknown field rejection | ✅ Yes | Pydantic v2 rejects extra fields by default |

### 6.4 Frontend Input Sanitization

**File:** `apps/web/lib/validation.ts`

| Check | Status | Detail |
|---|---|---|
| XSS sanitization | ✅ Yes | `sanitize()` escapes HTML entities |
| Email validation | ✅ Yes | Regex-based validation |
| Password strength | ✅ Yes | Length + complexity checks |
| URL validation | ✅ Yes | `validateUrl()` with protocol check |
| Safe redirect check | ✅ Yes | `isSafeRedirect()` prevents open redirects |

---

## 7. Cross-Site Scripting (XSS)

| Check | Status | Detail |
|---|---|---|
| Content-Security-Policy header | ✅ Yes | Restrictive CSP set in middleware |
| `X-Content-Type-Options: nosniff` | ✅ Yes | Prevents MIME sniffing |
| React auto-escaping | ✅ Yes | JSX auto-escapes by default |
| `dangerouslySetInnerHTML` usage | ⚠️ Unknown | Not audited — potential XSS vector |
| User input in `<a href>` | ⚠️ Risk | `ProfileMenuItem` uses `href` prop — verify no `javascript:` URLs |
| `style-src 'unsafe-inline'` | ⚠️ Risk | Allows inline styles — could be exploited |

### CSP Analysis

**File:** `apps/web/middleware.ts`

```
default-src 'self'
script-src 'self' 'unsafe-eval' 'unsafe-inline' (dev) / 'self' (prod)
style-src 'self' 'unsafe-inline'
img-src 'self' data: blob:
font-src 'self' data:
connect-src 'self' <apiUrl>
frame-ancestors 'none'
```

**Concerns:**
- `'unsafe-eval'` in development mode — ensure never leaks to production
- `'unsafe-inline'` for styles — consider using nonces or hashes
- Missing `form-action` directive
- Missing `base-uri` directive

---

## 8. Cross-Site Request Forgery (CSRF)

**File:** `services/api/app/main.py`

| Check | Status | Detail |
|---|---|---|
| CSRF protection enabled | ✅ Yes | Double-submit pattern implemented |
| Header validation | ✅ Yes | `X-CSRF-Token` header must match `csrf_token` cookie |
| GET/HEAD/OPTIONS exempt | ✅ Yes | Only mutating methods require CSRF |
| Public endpoints exempt | ✅ Yes | Auth endpoints, webhooks, health exempt |
| Token generation | ✅ Yes | `secrets.token_hex(32)` — cryptographically secure |
| Token expiry | ✅ Yes | `max_age=settings.REFRESH_COOKIE_MAX_AGE` (7 days) |

### CSRF Exemptions

```
/api/v1/auth/login
/api/v1/auth/signup
/api/v1/auth/refresh
/api/v1/auth/forgot-password
/api/v1/auth/reset-password
/api/v1/auth/verify-email
/api/v1/auth/csrf-token
/api/v1/channels/webhook/*
/health
```

**Concern:** The `/api/v1/auth/refresh` exemption is correct (cookie-only), but verify no state-changing operations happen via GET.

---

## 9. API Security

### 9.1 Rate Limiting

**File:** `services/api/app/modules/auth/rate_limit.py` + `apps/web/middleware.ts`

| Endpoint | Limit | Window | Backend |
|---|---|---|---|
| `/auth/signup` | 5 requests | 60s | Redis + in-process fallback |
| `/auth/login` | 10 requests | 60s | Redis + in-process fallback |
| `/auth/refresh` | 30 requests | 60s | Redis + in-process fallback |
| `/auth/forgot-password` | 3 requests | 60s | Redis + in-process fallback |
| `/auth/reset-password` | 3 requests | 60s | Redis + in-process fallback |
| Frontend (Next.js) | 100 req (prod) / 500 (dev) | 60s | In-memory (per-process) |

**Concerns:**
- ⚠️ Frontend rate limiter is per-process — doesn't work across multiple server instances
- ⚠️ In-process fallback loses state on restart
- ⚠️ No rate limiting on LLM/RAG/TTS/STT endpoints (potential abuse)

### 9.2 CORS Configuration

**File:** `services/api/app/main.py` + `services/api/app/config.py`

| Check | Status | Detail |
|---|---|---|
| Origins explicitly listed | ✅ Yes | `CORS_ORIGINS: ["http://localhost:3000"]` |
| Credentials allowed | ✅ Yes | `allow_credentials=True` |
| Wildcard origin | ✅ No | Not using `"*"` with credentials |
| Allowed methods | ✅ Restricted | `GET, POST, PUT, DELETE, PATCH` |
| Allowed headers | ✅ Restricted | `Content-Type, Authorization, X-CSRF-Token` |

### 9.3 TrustedHost Middleware

**File:** `services/api/app/main.py`

| Check | Status | Detail |
|---|---|---|
| Host header validation | ✅ Yes | `TrustedHostMiddleware` configured |
| Allowed hosts | ⚠️ Dev only | `["localhost", "127.0.0.1"]` — must update for production |

### 9.4 Request Size Limits

| Check | Status | Detail |
|---|---|---|
| Webhook body limit | ✅ 1MB | `MAX_WEBHOOK_BODY_BYTES = 1_000_000` |
| File upload limit | ⚠️ Config | `MAX_UPLOAD_SIZE_MB: 100` — not enforced in code |
| General API body limit | ❌ Missing | No global request body size limit |

---

## 10. Frontend Security

### 10.1 Next.js Security Headers

**File:** `apps/web/next.config.ts` + `apps/web/middleware.ts`

| Header | Value | Status |
|---|---|---|
| `X-DNS-Prefetch-Control` | `on` | ✅ Performance optimization |
| `Cross-Origin-Opener-Policy` | `same-origin` | ✅ Prevents cross-origin attacks |
| `Cross-Origin-Embedder-Policy` | `credentialless` | ✅ Prevents cross-origin leaks |
| `X-Content-Type-Options` | `nosniff` | ✅ Prevents MIME sniffing |
| `X-Frame-Options` | `DENY` | ✅ Prevents clickjacking |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | ✅ Limits referrer data |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=()` | ✅ Disables sensitive APIs |
| `Strict-Transport-Security` | `max-age=63072000; includeSubDomains; preload` | ✅ Forces HTTPS |
| `Content-Security-Policy` | See Section 7 | ✅ Restrictive |
| `Cache-Control` (API) | `no-store, no-cache, must-revalidate` | ✅ Prevents caching sensitive data |
| `poweredByHeader` | `false` | ✅ Hides framework identity |

### 10.2 Client-Side Auth Guard

**File:** `apps/web/components/AuthGuard.tsx`

| Check | Status | Detail |
|---|---|---|
| Protected routes checked | ✅ Yes | Dashboard routes wrapped in `AuthGuard` |
| Redirect on unauthenticated | ✅ Yes | `router.replace("/login")` |
| Loading state handling | ✅ Yes | Shows spinner during auth check |

### 10.3 Server-Side Auth Guard

**File:** `apps/web/middleware.ts`

| Check | Status | Detail |
|---|---|---|
| Dashboard redirect | ✅ Yes | No `refresh_token` cookie → redirect to `/login` |
| Secure cookie check | ⚠️ Weak | Only checks cookie existence, not validity |

### 10.4 Token Storage

**File:** `apps/web/lib/auth-context.tsx`

| Check | Status | Detail |
|---|---|---|
| Access token storage | ⚠️ Memory only | `_accessToken` in module scope — lost on page refresh |
| Refresh token storage | ✅ httpOnly cookie | Not accessible via JavaScript |
| CSRF token extraction | ✅ From cookie | `getCsrfToken()` reads `csrf_token` cookie |
| Auto-refresh on 401 | ✅ Yes | `tryRefresh()` called on 401 responses |
| Redirect loop prevention | ✅ Yes | Skips redirect on auth pages |

### 10.5 Security Concerns in Frontend

| Issue | Risk | Detail |
|---|---|---|
| `access_token` in memory | ⚠️ Medium | XSS could steal it — consider httpOnly cookie for access tokens too |
| `process.env` exposure | ⚠️ Low | `NEXT_PUBLIC_API_URL` is client-exposed — verify no secrets leak |
| `'unsafe-eval'` in dev CSP | ⚠️ Low | Ensure production never includes `unsafe-eval` |

---

## 11. Infrastructure & Deployment

### 11.1 Database Configuration

**File:** `services/api/app/database.py`

| Check | Status | Detail |
|---|---|---|
| Async driver | ✅ asyncpg | PostgreSQL async driver |
| Connection pooling | ✅ Yes | `create_async_engine` with default pool |
| Echo disabled | ✅ Yes | `echo=False` — no SQL logging in production |
| SSL/TLS | ⚠️ Not configured | No `ssl=require` in DATABASE_URL |
| Connection timeout | ⚠️ Default | No explicit timeout configured |

### 11.2 Docker

**File:** `docker-compose.yml`

| Check | Status | Detail |
|---|---|---|
| Services defined | ❌ Empty | `services: {}` — not yet configured |
| Secrets in compose | ⚠️ N/A | No compose secrets management |
| Non-root user | ⚠️ N/A | Dockerfile not present |

### 11.3 Environment Separation

| Check | Status | Detail |
|---|---|---|
| Development config | ✅ `.env` | Local development settings |
| Production config | ❌ Missing | No production-specific configuration |
| Staging config | ❌ Missing | No staging environment configuration |
| CI/CD secrets | ❌ Unknown | No CI/CD pipeline audited |

---

## 12. Data Protection & Privacy

### 12.1 PII Handling

| Data Type | Storage | Protection |
|---|---|---|
| Email | DB (plaintext) | Unique index, used for auth |
| Password | DB (hashed) | bcrypt hash only |
| Name | DB (plaintext) | Used for display |
| IP Address | DB (login_attempts, refresh_tokens) | Truncated to 45 chars (IPv6 max) |
| User Agent | DB (refresh_tokens) | Truncated to 500 chars |
| OAuth Tokens | DB (encrypted) | Fernet encryption |
| Business Type | DB (plaintext) | Optional, user-provided |

### 12.2 Data Retention

| Data | Retention | Cleanup |
|---|---|---|
| Login attempts | 30 days | `cleanup_expired_data()` on startup |
| Refresh tokens | 7 days after expiry | `cleanup_expired_data()` on startup |
| Event outbox | Configurable | `OutboxWorker` cleanup |

### 12.3 Privacy Concerns

| Issue | Risk | Detail |
|---|---|---|
| Email in login attempts | ⚠️ Low | Stored in plaintext — consider hashing |
| IP address logging | ⚠️ Low | May require GDPR compliance |
| No data export/delete API | ⚠️ Medium | No user data portability endpoint |
| No consent tracking | ⚠️ Medium | `newsletter` field exists but no consent audit trail |

---

## 13. Error Handling & Logging

### 13.1 Error Messages

**File:** `services/api/app/modules/auth/`

| Check | Status | Detail |
|---|---|---|
| Generic auth error messages | ✅ Yes | `"Invalid email or password"` (no user enumeration) |
| Email existence disclosure | ⚠️ Partial | `"Email already registered"` confirms email exists |
| Stack traces in responses | ✅ No | Proper HTTP exceptions with safe messages |
| Debug mode in production | ✅ No | `echo=False` on engine |

### 13.2 Security Event Logging

**File:** `services/api/app/modules/auth/events.py`

| Event Type | Logged |
|---|---|
| `signup` | ✅ Yes |
| `login` | ✅ Yes |
| `login_failed` | ✅ Yes |
| `logout` | ✅ Yes |
| `password_reset` | ✅ Yes |
| `password_reset_request` | ✅ Yes |
| `email_verified` | ✅ Yes |
| `token_refresh` | ✅ Yes |
| `account_locked` | ✅ Yes |

**Note:** Events use the outbox pattern — resilient to Kafka outages with auto-retry.

### 13.3 Logging Concerns

| Issue | Risk | Detail |
|---|---|---|
| No structured JSON logging | ⚠️ Low | `print()` used for startup errors |
| No log aggregation configured | ⚠️ Low | No ELK/Datadog/Sentry integration |
| No request ID tracking | ⚠️ Low | No correlation IDs for debugging |
| Auth events not persisted | ⚠️ Low | Outbox → Kafka, but no permanent audit table |

---

## 14. File Upload & Document Processing

### 14.1 Upload Handling

**File:** `services/api/app/modules/rag/router.py`

| Check | Status | Detail |
|---|---|---|
| Auth required | ✅ Yes | `Depends(get_current_user)` |
| User-scoped storage | ✅ Yes | Documents linked to user's databank |
| File type validation | ⚠️ Partial | Enum-based (`pdf, docx, txt, md, csv, xlsx, sql`) |
| File size limit | ⚠️ Config only | `MAX_UPLOAD_SIZE_MB: 100` — not enforced in code |
| Content-type validation | ❌ Missing | No MIME type verification |

### 14.2 Document Parsers

**Files:** `services/api/app/modules/rag/parsers/`

| Parser | Concern |
|---|---|
| `pdf.py` | Uses `pypdfium2` — memory safe for standard PDFs |
| `csv.py` | Uses stdlib `csv` — safe from injection |
| `docx.py` | Uses `python-docx` — safe for standard DOCX |
| `xlsx.py` | Uses `openpyxl` — safe for standard XLSX |
| `sql.py` | Parses INSERT statements — regex-based, not executing |
| `text.py` | UTF-8 decode with `errors="replace"` — safe |

### 14.3 Security Concerns

| Issue | Risk | Detail |
|---|---|---|
| No malware scanning | ⚠️ Medium | Uploaded files not scanned for malware |
| No content-type verification | ⚠️ Medium | File extension only, not MIME type |
| Zip bomb potential | ⚠️ Low | Large files could cause memory issues |
| Path traversal in filenames | ✅ Safe | Filenames stored as-is, not used in file paths |

---

## 15. Webhook Security

### 15.1 Webhook Endpoints

**File:** `services/api/app/modules/channels/router.py`

| Check | Status | Detail |
|---|---|---|
| Signature verification | ✅ Yes | Platform-specific HMAC verification |
| Body size limit | ✅ 1MB | `MAX_WEBHOOK_BODY_BYTES = 1_000_000` |
| Signature algorithm | ✅ HMAC-SHA256 | Used for all platforms |
| Constant-time comparison | ✅ Yes | `hmac.compare_digest()` |
| Platform-specific headers | ✅ Yes | Different header per platform |

### 15.2 Supported Platforms

| Platform | Signature Header | Status |
|---|---|---|
| Facebook | `x-hub-signature-256` | ✅ Implemented |
| Instagram | `x-hub-signature-256` | ✅ Implemented |
| X/Twitter | `x-twitter-webhooks-signature` | ✅ Implemented |
| Telegram | `x-telegram-bot-api-secret-token` | ✅ Implemented |
| WhatsApp | `x-hub-signature-256` | ✅ Implemented |
| LinkedIn | `x-linkedin-signature` | ✅ Implemented |

### 15.3 Webhook Concerns

| Issue | Risk | Detail |
|---|---|---|
| No replay protection | ⚠️ Medium | No timestamp/nonce validation |
| Signature optional if no secret | ⚠️ Medium | `elif not channel:` logs warning but continues |
| No IP allowlisting | ⚠️ Low | Platform IPs not validated |

---

## 16. Dependencies & Supply Chain

### 16.1 Python Dependencies (pyproject.toml)

| Package | Version Constraint | Security Notes |
|---|---|---|
| `fastapi` | ≥0.115 | Well-maintained, active security |
| `sqlalchemy[asyncio]` | ≥2.0 | Parameterized queries by default |
| `pyjwt` | ≥2.10 | Current, no known CVEs |
| `bcrypt` | ≥4.2 | Industry standard |
| `cryptography` | ≥43.0 | Well-maintained |
| `httpx` | ≥0.27 | Current |
| `openai` | ≥1.60 | Well-maintained |

### 16.2 Frontend Dependencies

| Package | Security Notes |
|---|---|
| `next` | Well-maintained, active security |
| `react` | Well-maintained |
| `lucide-react` | Icons only, minimal risk |
| `@heroicons/react` | Icons only, minimal risk |

### 16.3 Supply Chain Concerns

| Issue | Risk | Detail |
|---|---|---|
| No `npm audit` in CI | ⚠️ Medium | No automated vulnerability scanning |
| No `pip-audit` in CI | ⚠️ Medium | No automated Python vulnerability scanning |
| No lockfile for Python | ⚠️ Medium | `uv.lock` present but verify pinning |
| No dependency review | ⚠️ Low | No process for reviewing new dependencies |

---

## 17. Detailed Findings

### 🔴 CRITICAL

#### C-01: JWT Secret Exposed in Git Repository — ❌ NOT REPRODUCIBLE (reclassified)
- **File:** `services/api/.env`
- **Verified:** `.env` is git-ignored; the cited secret is **not in the repo**. Original CRITICAL downgraded.
- **Residual:** `alembic.ini:4` still commits a dev DB password `mentee` (tracked) — see **G6**.
- **Remediation:** Rotate DB password, scrub `alembic.ini` from history, inject DB URL via env.

#### C-02: Missing Token Blacklisting in Auth Middleware — ⚠️ CONFIRMED (see G1)
- **File:** `services/api/app/core/deps.py`
- **Risk:** `is_token_blacklisted()` exists but is **not called** in `get_current_user` → revoked access tokens remain valid until expiry.
- **Impact:** Logged-out users can still access API
- **Remediation:** Add `is_token_blacklisted(payload["jti"])` check

#### C-03: Access Token Returned in Response Body
- **File:** `services/api/app/modules/auth/router.py`
- **Risk:** XSS could steal access token from DOM/storage
- **Impact:** Token theft → unauthorized API access
- **Remediation:** Move access tokens to httpOnly cookies

---

### 🟡 MEDIUM

#### M-01: IP Spoofing via X-Forwarded-For
- **File:** `services/api/app/modules/auth/router.py:31-38`
- **Risk:** Rate limiting bypassed by spoofing headers
- **Impact:** Brute-force attacks possible
- **Remediation:** Only trust X-Forwarded-For from known reverse proxy

#### M-02: No Password Complexity Requirements
- **File:** `services/api/app/modules/auth/schemas.py:8`
- **Risk:** Weak passwords allowed (e.g., "12345678")
- **Impact:** Credential stuffing success rate increases
- **Remediation:** Require uppercase, lowercase, number, special char

#### M-03: No Rate Limiting on LLM/RAG/TTS/STT Endpoints
- **Files:** `services/api/app/modules/llm/router.py`, etc.
- **Risk:** API abuse, excessive LLM costs
- **Impact:** Financial loss, service degradation
- **Remediation:** Add per-user rate limits on compute-heavy endpoints

#### M-04: In-Process Rate Limiter State Loss
- **File:** `services/api/app/modules/auth/rate_limit.py:46`
- **Risk:** Rate limit resets on server restart
- **Impact:** Attackers can brute-force after restart
- **Remediation:** Redis-only rate limiting in production

#### M-05: Frontend Rate Limiter Per-Process Only
- **File:** `apps/web/middleware.ts:2`
- **Risk:** Doesn't work across multiple server instances
- **Impact:** Rate limiting ineffective in scaled deployments
- **Remediation:** Use Redis-based rate limiting

#### M-06: No Global Request Body Size Limit
- **File:** `services/api/app/main.py`
- **Risk:** Large payloads could cause DoS
- **Impact:** Server memory exhaustion
- **Remediation:** Configure `body_limit` in FastAPI

#### M-07: No Data Export/Delete API (GDPR)
- **Risk:** User data portability not supported
- **Impact:** GDPR compliance gap
- **Remediation:** Add `/api/v1/user/export` and `/api/v1/user/delete` endpoints

#### M-08: TrustedHost Only Configured for Localhost
- **File:** `services/api/app/config.py`
- **Risk:** Will break in production if not updated
- **Impact:** All requests rejected in production
- **Remediation:** Add production domains to `ALLOWED_HOSTS`

---

### 🟢 LOW

#### L-01: Email Existence Disclosure
- **File:** `services/api/app/modules/auth/service.py:65`
- **Risk:** "Email already registered" confirms email exists
- **Impact:** User enumeration possible
- **Remediation:** Use generic message like "If email exists, a link was sent"

#### L-02: No Webhook Replay Protection
- **File:** `services/api/app/modules/channels/router.py`
- **Risk:** Old webhooks could be replayed
- **Impact:** Duplicate message processing
- **Remediation:** Add timestamp validation

#### L-03: CSP `unsafe-inline` for Styles
- **File:** `apps/web/middleware.ts`
- **Risk:** Could enable style injection
- **Impact:** Limited (styles can't execute JS)
- **Remediation:** Use nonces or hashes

#### L-04: No Malware Scanning on Uploads
- **File:** `services/api/app/modules/rag/router.py`
- **Risk:** Malicious files could be uploaded
- **Impact:** Server compromise if file processed unsafely
- **Remediation:** Integrate ClamAV or similar

#### L-05: No Content-Type Verification on Uploads
- **File:** `services/api/app/modules/rag/router.py`
- **Risk:** File extension spoofing
- **Impact:** Unexpected file processing
- **Remediation:** Verify MIME type against magic bytes

#### L-06: Database Connection No SSL
- **File:** `services/api/app/database.py`
- **Risk:** DB traffic could be intercepted
- **Impact:** Data leakage in transit
- **Remediation:** Add `ssl=require` to DATABASE_URL

---

### ℹ️ INFORMATIONAL

#### I-01: No Structured Logging
- No JSON structured logging for log aggregation

#### I-02: No Request ID Tracking
- No correlation IDs for debugging distributed requests

#### I-03: No CI/CD Security Scanning
- No SAST/DAST tools in pipeline

#### I-04: No Penetration Testing
- No evidence of regular pen testing

---

## 17.5 Verified Remaining Gaps (2026-08-13 Reconciliation)

These are the gaps **actually present in the current code** after reconciling with `FIXES-NEEDED.md`. Items A1, A2, A14, B24 from `FIXES-NEEDED.md` are **resolved** and not repeated here.

### 🔴 HIGH

#### G1: Token Blacklist Not Enforced in `get_current_user`
- **File:** `services/api/app/core/deps.py:20-44` (blacklist fn: `app/modules/auth/rate_limit.py:55`)
- **Risk:** `is_token_blacklisted()` exists but is never called in `get_current_user`. Logout/reset blacklist the JTI, yet revoked **access tokens remain valid until 15-min expiry**.
- **Fix:** Add `if await is_token_blacklisted(payload.get("jti")): raise 401` after decode in `get_current_user`.

#### G2: Access Token Returned in JSON Response Body
- **File:** `services/api/app/modules/auth/router.py:85-88`, `app/modules/auth/service.py:154`
- **Risk:** XSS can steal the access token from the response body (not httpOnly).
- **Fix:** Return access token via httpOnly cookie, or accept the risk behind a strict CSP.

### 🟡 MEDIUM

#### G3: Webhook Processes Without Signature When No Secret Configured
- **File:** `services/api/app/modules/channels/router.py:204-212`
- **Risk:** If a channel has no `webhook_secret`, signature verification is skipped and the payload is still processed → unauthenticated message injection for misconfigured channels.
- **Fix:** Require `webhook_secret` to process non-verify webhook requests; reject otherwise.

#### G4: Client IP Spoofable via `X-Forwarded-For`
- **File:** `services/api/app/modules/auth/router.py:34-36`
- **Risk:** Leftmost `X-Forwarded-For` is trusted directly → IP-based rate limits bypassed unless behind a trusted proxy.
- **Fix:** Only trust `X-Forwarded-For` from a configured reverse proxy; otherwise use `request.client.host`.

#### G5: Rate-Limit In-Process Fallback Not Scale-Safe
- **File:** `services/api/app/modules/auth/rate_limit.py:35-42`
- **Risk:** Falls back to an in-process dict that resets on restart and is per-instance only → limits ineffective across multiple instances at scale.
- **Fix:** Redis-only limiter in production; keep in-process only for local dev.

#### G6: Dev DB Password Committed + No DB SSL
- **File:** `services/api/alembic.ini:4`, `app/database.py:8`
- **Risk:** `postgres:mentee@localhost` is tracked in git (low real risk = localhost dev) and DB connection has no `ssl=require`.
- **Fix:** Rotate password, scrub from history, inject `DATABASE_URL` via env; add `ssl=require` for prod.

#### G7: No Per-User LLM / RAG Spend Caps
- **File:** `services/api/app/modules/llm/*`, `rag/*`
- **Risk:** Unbounded LLM/RAG calls → cost-abuse / bankruptcy risk at scale.
- **Fix:** Per-user monthly quotas + concurrency limits.

### 🟢 LOW

#### G8: No Global Body-Size Limit / Upload MIME Check
- **File:** `services/api/app/main.py`, `app/modules/rag/router.py`
- **Risk:** Large payloads (DoS); extension-only upload validation.
- **Fix:** Enforce global `body_limit`; verify magic bytes for uploads.

#### G9: No Password Complexity / Email Enumeration
- **File:** `services/api/app/modules/auth/schemas.py`, `service.py:43`
- **Risk:** Weak passwords allowed; "Email already registered" discloses existence.
- **Fix:** Add complexity rules; use generic signup messages.

---

## 18. Remediation Roadmap

### 🔴 Immediate (Within 1 Week)

| Priority | Issue | Action | Effort |
|---|---|---|---|
| P0 | C-01 | Rotate JWT_SECRET, remove `.env` from git history | 1 hour |
| P0 | C-02 | Add token blacklist check to `get_current_user` | 2 hours |
| P1 | C-03 | Move access tokens to httpOnly cookies | 4 hours |
| P1 | M-08 | Update `ALLOWED_HOSTS` for production | 30 min |

### 🟡 Short-term (Within 1 Month)

| Priority | Issue | Action | Effort |
|---|---|---|---|
| P2 | M-01 | Add reverse proxy IP validation | 2 hours |
| P2 | M-02 | Add password complexity requirements | 1 hour |
| P2 | M-03 | Add rate limiting on LLM/RAG endpoints | 4 hours |
| P2 | M-06 | Add global request body size limit | 1 hour |
| P2 | L-01 | Fix email existence disclosure | 30 min |

### 🟢 Medium-term (Within 3 Months)

| Priority | Issue | Action | Effort |
|---|---|---|---|
| P3 | M-07 | Add GDPR data export/delete endpoints | 8 hours |
| P3 | M-04 | Remove in-process rate limiter fallback | 2 hours |
| P3 | L-03 | Remove `unsafe-inline` from CSP | 4 hours |
| P3 | L-04 | Integrate malware scanning | 1 day |
| P3 | L-06 | Configure database SSL | 1 hour |

### ⚪ Long-term (Within 6 Months)

| Priority | Issue | Action | Effort |
|---|---|---|---|
| P4 | I-01 | Implement structured JSON logging | 1 day |
| P4 | I-02 | Add request ID tracking | 4 hours |
| P4 | I-03 | Add SAST/DAST to CI/CD | 2 days |
| P4 | I-04 | Schedule regular penetration testing | Ongoing |

---

## Appendix A: Security Checklist for Production Deployment

```bash
# Pre-deployment security checklist

# 1. Rotate JWT_SECRET
python -c "import secrets; print(secrets.token_urlsafe(64))"

# 2. Update .env with new secret
# JWT_SECRET=<new-secret>

# 3. Update ALLOWED_HOSTS
# ALLOWED_HOSTS=["yourdomain.com", "www.yourdomain.com"]

# 4. Update CORS_ORIGINS
# CORS_ORIGINS=["https://yourdomain.com"]

# 5. Verify .env is in .gitignore
cat .gitignore | grep ".env"

# 6. Run dependency audit
pip-audit
npm audit

# 7. Check for hardcoded secrets
grep -r "password\|secret\|token" --include="*.py" --include="*.ts" | grep -v "hash\|verify\|validate"

# 8. Verify SSL/TLS on database
# Update DATABASE_URL with ?ssl=require

# 9. Enable HTTPS on reverse proxy
# Configure nginx/caddy with TLS

# 10. Set up monitoring and alerting
# Configure Sentry, Datadog, or similar
```

---

## Appendix B: Security Headers Reference

```
# Recommended production headers

X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 0  # Deprecated, but harmless
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=()
Strict-Transport-Security: max-age=63072000; includeSubDomains; preload
Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self' https://api.yourdomain.com; frame-ancestors 'none'; form-action 'self'; base-uri 'self'
X-DNS-Prefetch-Control: on
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Embedder-Policy: credentialless
```

---

*Report generated by Buffy Security Audit — August 13, 2026*
*For questions or remediation assistance, contact your development team.*
