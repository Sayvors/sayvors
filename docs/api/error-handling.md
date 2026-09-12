# Error Handling

## Error Response Format

All errors follow a consistent format:

```json
{
  "detail": "Human-readable error message",
  "code": "ERROR_CODE",
  "status": 400,
  "meta": { "field": "email", "reason": "already_exists" }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `detail` | string | User-facing message |
| `code` | string | Machine-readable error code |
| `status` | integer | HTTP status code |
| `meta` | object | Optional additional context |

## HTTP Status Codes

| Code | Constant | Description |
|------|----------|-------------|
| 400 | `BAD_REQUEST` | Invalid request body/parameters |
| 401 | `UNAUTHORIZED` | Missing/invalid authentication |
| 403 | `FORBIDDEN` | Authenticated but not authorized (CSRF, permissions) |
| 404 | `NOT_FOUND` | Resource not found |
| 409 | `CONFLICT` | Resource conflict (duplicate, state) |
| 413 | `PAYLOAD_TOO_LARGE` | Request body exceeds limit |
| 422 | `UNPROCESSABLE_ENTITY` | Validation failed |
| 429 | `TOO_MANY_REQUESTS` | Rate limit exceeded |
| 500 | `INTERNAL_SERVER_ERROR` | Unexpected server error |
| 502 | `BAD_GATEWAY` | External API failure (Google, LLM, etc.) |
| 503 | `SERVICE_UNAVAILABLE` | Service temporarily unavailable |

## Error Codes

### Authentication Errors

| Code | Status | Description |
|------|--------|-------------|
| `INVALID_CREDENTIALS` | 401 | Wrong email/password |
| `TOKEN_EXPIRED` | 401 | Access token expired |
| `TOKEN_INVALID` | 401 | Malformed or tampered token |
| `TOKEN_REVOKED` | 401 | Token blacklisted (logout) |
| `REFRESH_TOKEN_EXPIRED` | 401 | Refresh token expired |
| `REFRESH_TOKEN_INVALID` | 401 | Refresh token not found/revoked |
| `EMAIL_NOT_VERIFIED` | 403 | Email verification required |
| `CSRF_VALIDATION_FAILED` | 403 | Missing/invalid CSRF token |
| `ACCOUNT_LOCKED` | 403 | Too many failed attempts |

### Validation Errors

| Code | Status | Description |
|------|--------|-------------|
| `VALIDATION_ERROR` | 422 | Pydantic validation failed |
| `INVALID_EMAIL` | 400 | Email format invalid |
| `WEAK_PASSWORD` | 400 | Password doesn't meet requirements |
| `INVALID_TOKEN` | 400 | Verification/reset token invalid |
| `TOKEN_EXPIRED` | 400 | Verification/reset token expired |

### Resource Errors

| Code | Status | Description |
|------|--------|-------------|
| `NOT_FOUND` | 404 | Resource doesn't exist |
| `ALREADY_EXISTS` | 409 | Duplicate resource (email, channel) |
| `CONFLICT` | 409 | State conflict (e.g., reply already posted) |
| `NOT_OWNER` | 403 | User doesn't own resource |

### External Service Errors

| Code | Status | Description |
|------|--------|-------------|
| `GOOGLE_API_ERROR` | 502 | Google Business Profile API failed |
| `LLM_PROVIDER_ERROR` | 502 | LLM provider (Groq, OpenAI, etc.) failed |
| `EMAIL_PROVIDER_ERROR` | 502 | Resend/email service failed |
| `KAFKA_UNAVAILABLE` | 503 | Kafka broker unreachable |
| `REDIS_UNAVAILABLE` | 503 | Redis unreachable |

## Validation Error Details (422)

```json
{
  "detail": "Validation failed",
  "code": "VALIDATION_ERROR",
  "status": 422,
  "errors": [
    {
      "field": "email",
      "message": "Invalid email format",
      "type": "value_error.email"
    },
    {
      "field": "password",
      "message": "Password must be at least 8 characters",
      "type": "value_error.any_str.min_length"
    }
  ]
}
```

## Client Error Handling

### TypeScript Error Classes

```typescript
class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    public detail: string,
    public meta?: Record<string, unknown>
  ) {
    super(detail);
    this.name = 'ApiError';
  }
  
  static fromResponse(response: Response, data: any): ApiError {
    return new ApiError(
      data.status || response.status,
      data.code || 'UNKNOWN_ERROR',
      data.detail || response.statusText,
      data.meta
    );
  }
}

class ValidationError extends ApiError {
  public errors: Array<{ field: string; message: string; type: string }>;
  
  constructor(data: any) {
    super(data.status, data.code, data.detail, data.meta);
    this.name = 'ValidationError';
    this.errors = data.errors || [];
  }
}
```

### Error Handling Wrapper

```typescript
async function handleApiError(response: Response): Promise<never> {
  const data = await response.json().catch(() => ({}));
  
  if (response.status === 422) {
    throw new ValidationError(data);
  }
  
  throw ApiError.fromResponse(response, data);
}

async function apiFetch(path: string, options: RequestInit = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    credentials: 'include',
  });
  
  if (!response.ok) {
    await handleApiError(response);
  }
  
  return response.json();
}
```

### React Error Boundary Integration

```tsx
function useApiError() {
  const [error, setError] = useState<ApiError | null>(null);
  
  const clearError = () => setError(null);
  
  const handleError = (err: unknown) => {
    if (err instanceof ApiError) {
      setError(err);
      
      // Auto-handle common cases
      if (err.status === 401 && err.code === 'TOKEN_EXPIRED') {
        refreshToken().then(() => {
          // Retry logic
        });
      }
    } else {
      setError(new ApiError(500, 'UNKNOWN', 'An unexpected error occurred'));
    }
  };
  
  return { error, clearError, handleError };
}
```

## Retry Logic

### Retryable Errors

| Code | Retry | Strategy |
|------|-------|----------|
| `TOO_MANY_REQUESTS` | Yes | Exponential backoff + `retry_after` |
| `BAD_GATEWAY` | Yes | Exponential backoff (max 3) |
| `SERVICE_UNAVAILABLE` | Yes | Exponential backoff (max 3) |
| `INTERNAL_SERVER_ERROR` | Yes | Exponential backoff (max 2) |
| `UNAUTHORIZED` (TOKEN_EXPIRED) | Once | Refresh token + retry |

### Non-Retryable Errors

| Code | Action |
|------|--------|
| `BAD_REQUEST` | Fix request |
| `UNAUTHORIZED` (invalid credentials) | Redirect to login |
| `FORBIDDEN` | Check permissions |
| `NOT_FOUND` | Handle gracefully |
| `CONFLICT` | Show conflict UI |
| `VALIDATION_ERROR` | Show field errors |

### Retry Implementation

```typescript
async function fetchWithRetry(
  path: string,
  options: RequestInit = {},
  maxRetries = 3
): Promise<any> {
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await apiFetch(path, options);
    } catch (error) {
      if (error instanceof ApiError) {
        const retryable = [
          'TOO_MANY_REQUESTS',
          'BAD_GATEWAY',
          'SERVICE_UNAVAILABLE',
          'INTERNAL_SERVER_ERROR'
        ].includes(error.code);
        
        const isAuthRetry = error.code === 'TOKEN_EXPIRED' && attempt === 0;
        
        if (!retryable && !isAuthRetry) {
          throw error;
        }
        
        if (isAuthRetry) {
          await refreshToken();
          continue; // Retry immediately after refresh
        }
        
        // Exponential backoff
        const waitMs = Math.min(1000 * 2 ** attempt, 30000);
        const jitter = waitMs * 0.1 * Math.random();
        await sleep(waitMs + jitter);
      } else {
        throw error;
      }
    }
  }
  throw new ApiError(500, 'MAX_RETRIES', 'Max retries exceeded');
}
```

## Logging & Monitoring

### Server-Side Error Logging

All 5xx errors are logged with:
- Request ID (for tracing)
- User ID (if authenticated)
- Stack trace
- Request context (path, method, IP)

### Client-Side Error Reporting

```typescript
function reportError(error: ApiError, context?: Record<string, any>) {
  // Send to error tracking (Sentry, etc.)
  if (window.Sentry) {
    window.Sentry.captureException(error, {
      extra: { ...context, apiError: error }
    });
  }
  
  // Log to console in development
  if (process.env.NODE_ENV === 'development') {
    console.error('API Error:', error);
  }
}
```

## Testing Error Scenarios

### Unit Test Example

```python
async def test_rate_limit_exceeded(client, auth_headers):
    # Make requests up to limit
    for _ in range(100):
        await client.get("/api/v1/locations/", headers=auth_headers)
    
    # Next request should be 429
    response = await client.get("/api/v1/locations/", headers=auth_headers)
    assert response.status_code == 429
    assert response.json()["code"] == "RATE_LIMIT_EXCEEDED"
```

### Integration Test Example

```python
async def test_invalid_token_returns_401(client):
    response = await client.get(
        "/api/v1/locations/",
        headers={"Authorization": "Bearer invalid-token"}
    )
    assert response.status_code == 401
    assert response.json()["code"] == "TOKEN_INVALID"
```