# API Overview

## Base URLs

| Environment | Base URL |
|-------------|----------|
| Development | `http://localhost:8000` |
| Staging | `https://staging-api.sayvors.com` |
| Production | `https://api.sayvors.com` |

All API endpoints are prefixed with `/api/v1`.

## Authentication

The API uses **JWT (JSON Web Tokens)** with **HTTP-only cookies** for authentication:

- **Access Token**: Short-lived (15 min), returned in response body
- **Refresh Token**: Long-lived (7 days), stored in HTTP-only cookie
- **CSRF Token**: Double-submit pattern, stored in accessible cookie

See [Authentication Guide](authentication.md) for details.

## Rate Limiting

| Endpoint Category | Limit | Window |
|-------------------|-------|--------|
| Auth (signup/login) | 5-10 req | 60 sec |
| Token refresh | 30 req | 60 sec |
| Password reset | 3 req | 60 sec |
| General API | 100 req | 60 sec |
| Webhooks | 1 MB payload | — |

See [Rate Limiting](rate-limiting.md) for full details.

## Response Format

### Success

```json
{
  "data": { ... },
  "meta": { "page": 1, "total": 100 }
}
```

### Error

```json
{
  "detail": "Human-readable error message",
  "code": "ERROR_CODE",
  "status": 400
}
```

### Pagination

List endpoints accept `limit` (1-100) and `offset` (>=0) query parameters.

```json
{
  "items": [...],
  "total": 150,
  "limit": 20,
  "offset": 0
}
```

## HTTP Status Codes

| Code | Meaning |
|------|---------|
| 200 | OK |
| 201 | Created |
| 204 | No Content |
| 400 | Bad Request |
| 401 | Unauthorized |
| 403 | Forbidden (CSRF, permissions) |
| 404 | Not Found |
| 409 | Conflict |
| 413 | Payload Too Large |
| 422 | Validation Error |
| 429 | Too Many Requests |
| 500 | Internal Server Error |
| 502 | Bad Gateway (external API failure) |
| 503 | Service Unavailable |

## CORS

Configured origins (see `CORS_ORIGINS` in config):
- Development: `http://localhost:3000`
- Production: configured per deployment

Allowed headers: `Content-Type`, `Authorization`, `X-CSRF-Token`

## Headers

### Request Headers

| Header | Required | Description |
|--------|----------|-------------|
| `Authorization` | Yes* | `Bearer <access_token>` |
| `X-CSRF-Token` | Yes** | CSRF token from cookie |
| `Content-Type` | Yes | `application/json` |

*Required for authenticated endpoints
**Required for state-changing methods (POST, PUT, PATCH, DELETE) except exempt paths

### Response Headers

| Header | Description |
|--------|-------------|
| `X-CSRF-Token` | New CSRF token (exposed for JS access) |
| `Set-Cookie` | Refresh token, CSRF token cookies |

## Cookie Configuration

| Cookie | Name | HttpOnly | Secure | SameSite | Max-Age |
|--------|------|----------|--------|----------|---------|
| Refresh Token | `refresh_token` | ✅ | ✅ | Lax | 7 days |
| CSRF Token | `csrf_token` | ❌ | ✅ | Lax | 7 days |

## Time Format

All timestamps use **ISO 8601** in UTC: `2024-01-15T10:30:00Z`

## Date/Time Query Parameters

- `days`: Integer, 1-365 (default: 30)
- Date ranges: Use `days` parameter for relative windows

## Idempotency

POST endpoints that create resources support idempotency via the `Idempotency-Key` header (optional).

## Versioning Policy

- Current version: `v1`
- Breaking changes → new version (`v2`)
- Non-breaking additions → same version
- Deprecation notice: 3 months minimum

## Support

- API Status: `GET /health`
- Documentation: `/docs` (Swagger), `/redoc` (ReDoc)
- Contact: api-support@sayvors.com