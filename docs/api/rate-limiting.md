# Rate Limiting

## Overview

The Sayvors API implements multi-layered rate limiting to prevent abuse and ensure fair usage.

## Rate Limit Policies

### Authentication Endpoints

| Endpoint | Limit | Window | Scope |
|----------|-------|--------|-------|
| `POST /auth/signup` | 5 | 60 sec | IP |
| `POST /auth/login` | 10 | 60 sec | IP |
| `POST /auth/login` | 10 | 60 sec | User (email) |
| `POST /auth/refresh` | 30 | 60 sec | IP |
| `POST /auth/forgot-password` | 3 | 60 sec | IP |
| `POST /auth/reset-password` | 3 | 60 sec | IP |
| `POST /auth/verify-otp` | 10 | 60 sec | IP |

### General API Endpoints

| Category | Limit | Window | Scope |
|----------|-------|--------|-------|
| Default | 100 | 60 sec | User |
| Analytics | 60 | 60 sec | User |
| LLM Chat | 30 | 60 sec | User |
| File Upload | 10 | 60 sec | User |
| Webhooks | 1000 | 60 sec | IP |

### Per-Endpoint Overrides

Specific endpoints may have custom limits defined in their route handlers.

## Rate Limit Headers

Responses include rate limit information:

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1705315800
```

- `X-RateLimit-Limit`: Maximum requests allowed in window
- `X-RateLimit-Remaining`: Requests remaining in current window
- `X-RateLimit-Reset`: Unix timestamp when window resets

## Exceeding Limits

### HTTP 429 Response

```json
{
  "detail": "Too many requests. Try again later.",
  "code": "RATE_LIMIT_EXCEEDED",
  "status": 429,
  "retry_after": 45
}
```

- `retry_after`: Seconds until next request allowed

### Client Handling

```typescript
async function handleRateLimit(response: Response) {
  if (response.status === 429) {
    const data = await response.json();
    const waitMs = (data.retry_after || 60) * 1000;
    
    // Exponential backoff with jitter
    const backoff = waitMs * (1 + Math.random() * 0.5);
    
    await sleep(backoff);
    return true; // Retry
  }
  return false;
}
```

## Implementation Details

### Redis-Backed (Production)

- Uses Redis sorted sets for sliding window
- Keys: `ratelimit:{scope}:{identifier}`
- Automatic cleanup of expired entries

### In-Memory (Development/Fallback)

- Uses in-memory store when Redis unavailable
- Not shared across instances
- `AUTH_RATE_LIMIT_FAIL_CLOSED=true` blocks requests when Redis down

### Trusted Proxies

IP detection respects `TRUSTED_PROXIES` configuration:

```python
TRUSTED_PROXIES = ["127.0.0.1", "::1", "10.0.0.0/8"]
```

- Only trusts `X-Forwarded-For` / `X-Real-IP` from trusted proxies
- Prevents IP spoofing for rate limits
- Rightmost XFF entry used (closest trusted proxy)

## Best Practices

### For API Consumers

1. **Cache responses** - Don't re-fetch unchanged data
2. **Batch requests** - Use list endpoints with pagination
3. **Implement backoff** - Exponential backoff on 429
4. **Monitor headers** - Track `X-RateLimit-Remaining`
5. **Use webhooks** - Instead of polling for updates

### For Developers

1. **Test limits** - Verify behavior in staging
2. **Set appropriate limits** - Balance UX vs protection
3. **Log violations** - Alert on repeated 429s
4. **Whitelist partners** - Configure higher limits for trusted integrations

## Configuration

Environment variables:

```bash
# Auth rate limits (per endpoint, override in code)
MAX_LOGIN_ATTEMPTS=5
LOCKOUT_MINUTES=15

# Redis
REDIS_URL=redis://localhost:6379/0
AUTH_RATE_LIMIT_FAIL_CLOSED=true

# Trusted proxies for IP detection
TRUSTED_PROXIES=["127.0.0.1", "::1", "10.0.0.0/8"]
```

## Monitoring

### Key Metrics

- Rate limit hits (429 responses)
- Rate limit remaining (distribution)
- Redis latency for rate limit checks
- Lockout events

### Alerting

- Alert on > 10% 429 rate
- Alert on Redis unavailable (fail-closed mode)
- Alert on repeated lockouts for same user/IP

## Custom Limits

To add custom rate limits to new endpoints:

```python
from ..auth.rate_limit import rate_limit

@router.post("/my-endpoint")
async def my_endpoint(request: Request, ...):
    ip = get_client_ip(request)
    if not await rate_limit(f"my-endpoint:{ip}", 20, 60):
        raise HTTPException(429, "Rate limit exceeded")
    ...
```

The `rate_limit(key, limit, window_seconds)` function returns `True` if allowed, `False` if limited.