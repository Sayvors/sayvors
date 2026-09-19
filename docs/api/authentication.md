# Authentication Guide

## Overview

The Sayvors API uses **JWT (JSON Web Tokens)** with **HTTP-only cookies** for secure authentication:

- **Access Token**: Short-lived (15 minutes), used for API authorization
- **Refresh Token**: Long-lived (7 days), stored in HTTP-only cookie
- **CSRF Token**: Double-submit pattern for state-changing requests

## Token Flow

```
┌─────────────┐     POST /login      ┌─────────────┐
│   Client    │ ──────────────────▶ │    API      │
└─────────────┘ ◀────────────────── │             │
       │                              │ 1. Validate │
       │  Set-Cookie: refresh_token   │ 2. Create   │
       │  Set-Cookie: csrf_token      │    tokens   │
       │  Body: access_token          │ 3. Return   │
       │                              └─────────────┘
       ▼
┌─────────────┐     GET /api/v1/...  ┌─────────────┐
│   Client    │ ──────────────────▶ │    API      │
└─────────────┘ ◀────────────────── │             │
       │                              │ 1. Verify   │
       │  Authorization: Bearer       │    access   │
       │  X-CSRF-Token: ...           │ 2. Verify   │
       │                              │    CSRF     │
       ▼                              └─────────────┘
```

## Login Flow

### 1. User Login

```http
POST /api/v1/auth/login
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "securepassword123"
}
```

**Response (200):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user": { "id": "...", "email": "...", ... }
}
```

**Cookies Set:**
```
Set-Cookie: refresh_token=eyJhbGciOiJIUzI1NiIs...; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=604800
Set-Cookie: csrf_token=a1b2c3d4e5f6...; Secure; SameSite=Lax; Path=/; Max-Age=604800
```

### 2. Using Access Token

```http
GET /api/v1/locations/
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### 3. State-Changing Requests (CSRF)

```http
POST /api/v1/posts/
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
X-CSRF-Token: a1b2c3d4e5f6...
Content-Type: application/json

{ "listing_id": "...", "content": "Hello!" }
```

## Token Refresh

### Automatic Refresh (Recommended)

The client should proactively refresh before expiry (e.g., at 10 minutes):

```http
POST /api/v1/auth/refresh
Cookie: refresh_token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

**Response (200):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user": { ... }
}
```

**New Cookies Set:**
```
Set-Cookie: refresh_token=new_token...; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=604800
Set-Cookie: csrf_token=new_csrf...; Secure; SameSite=Lax; Path=/; Max-Age=604800
```

### Refresh Token Rotation

Each refresh generates a **new refresh token** (rotation). Old tokens are invalidated.

## Logout

### Single Device
```http
POST /api/v1/auth/logout
Authorization: Bearer ...
X-CSRF-Token: ...
Content-Type: application/json

{ "refresh_token": "...", "all_devices": false }
```

### All Devices
```http
POST /api/v1/auth/logout
Authorization: Bearer ...
X-CSRF-Token: ...
Content-Type: application/json

{ "all_devices": true }
```

## CSRF Protection

### Double-Submit Cookie Pattern

1. Server sets `csrf_token` cookie (accessible to JS)
2. Client reads cookie and sends in `X-CSRF-Token` header
3. Server validates header matches cookie

### Exempt Paths (No CSRF Required)

- `GET`, `HEAD`, `OPTIONS` requests
- `/api/v1/auth/login`
- `/api/v1/auth/signup`
- `/api/v1/auth/refresh`
- `/api/v1/auth/forgot-password`
- `/api/v1/auth/reset-password`
- `/api/v1/auth/verify-email`
- `/api/v1/auth/verify-otp`
- `/api/v1/auth/csrf-token`
- `/api/v1/email/otp/`
- `/api/v1/channels/webhook/`
- `/health`

### Getting CSRF Token

```http
POST /api/v1/auth/csrf-token
```

**Response:**
```json
{ "csrf_token": "a1b2c3d4e5f6..." }
```

Cookie is also set automatically.

## Password Reset Flow

### 1. Request Reset
```http
POST /api/v1/auth/forgot-password
Content-Type: application/json

{ "email": "user@example.com" }
```

### 2. User Clicks Email Link
Link format: `https://app.sayvors.com/reset-password?token=...`

### 3. Reset Password
```http
POST /api/v1/auth/reset-password
Content-Type: application/json

{ "token": "...", "password": "newsecurepassword123" }
```

## Email Verification Flow

### 1. Signup (Returns Verification Token)
```http
POST /api/v1/auth/signup
...
```

Response includes `verification_token` (also emailed).

### 2. Verify Email
```http
POST /api/v1/auth/verify-email
Content-Type: application/json

{ "token": "..." }
```

### 3. OTP Verification (Alternative)
```http
POST /api/v1/auth/verify-otp
Content-Type: application/json

{ "email": "user@example.com", "code": "123456" }
```

## Token Details

### Access Token Payload
```json
{
  "sub": "user-uuid",
  "exp": 1705315800,
  "jti": "a1b2c3d4e5f6...",
  "type": "access"
}
```

- `sub`: User ID
- `exp`: Expiration (Unix timestamp)
- `jti`: Unique token ID (for revocation)
- `type`: "access"

### Refresh Token Payload
```json
{
  "sub": "user-uuid",
  "exp": 1705834200,
  "jti": "f6e5d4c3b2a1...",
  "type": "refresh"
}
```

### Email Verification Token
```json
{
  "sub": "user-uuid",
  "exp": 1705402200,
  "type": "email_verify"
}
```

### Password Reset Token
```json
{
  "sub": "user-uuid",
  "exp": 1705319400,
  "type": "password_reset"
}
```

## Security Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `JWT_SECRET` | Signing secret (min 64 chars) | Required |
| `JWT_ALGORITHM` | Signing algorithm | `HS256` |
| `JWT_ACCESS_EXPIRATION_MINUTES` | Access token TTL | `15` |
| `JWT_REFRESH_EXPIRATION_DAYS` | Refresh token TTL | `7` |
| `CSRF_COOKIE_NAME` | CSRF cookie name | `csrf_token` |
| `REFRESH_COOKIE_NAME` | Refresh cookie name | `refresh_token` |
| `REFRESH_COOKIE_MAX_AGE` | Refresh cookie max age (sec) | `604800` |
| `AUTH_RATE_LIMIT_FAIL_CLOSED` | Fail closed when Redis down | `true` |
| `TRUSTED_PROXIES` | Trusted proxy IPs/CIDRs | `["127.0.0.1", "::1"]` |

### Cookie Security

| Attribute | Value | Purpose |
|-----------|-------|---------|
| `HttpOnly` | ✅ (refresh) / ❌ (CSRF) | Prevent XSS access to refresh token |
| `Secure` | ✅ | HTTPS only |
| `SameSite` | `Lax` | CSRF protection, allows top-level nav |
| `Path` | `/` | Available on all paths |

## Rate Limiting on Auth

| Endpoint | Limit | Window |
|----------|-------|--------|
| `/signup` | 5 req | 60 sec (per IP) |
| `/login` | 10 req | 60 sec (per IP) |
| `/login` | 10 req | 60 sec (per user) |
| `/refresh` | 30 req | 60 sec (per IP) |
| `/forgot-password` | 3 req | 60 sec (per IP) |
| `/reset-password` | 3 req | 60 sec (per IP) |
| `/verify-otp` | 10 req | 60 sec (per IP) |

Uses Redis for distributed rate limiting. Fails closed when Redis unavailable (configurable).

## Account Lockout

- **Max Attempts**: 5 failed logins
- **Lockout Duration**: 15 minutes
- Tracked per IP + per user identity

## Session Management

### List Sessions
```http
GET /api/v1/auth/sessions
Authorization: Bearer ...
```

**Response:**
```json
{
  "sessions": [
    {
      "id": "session-uuid",
      "user_agent": "Mozilla/5.0...",
      "ip": "192.168.1.1",
      "created_at": "2024-01-15T10:30:00Z",
      "last_used": "2024-01-15T10:35:00Z",
      "current": true
    }
  ]
}
```

### Revoke Sessions
Use `all_devices: true` in logout to revoke all sessions.

## Client Implementation Guide

### JavaScript/TypeScript (Fetch)

```typescript
const API_BASE = 'http://localhost:8000/api/v1';

async function apiFetch(path: string, options: RequestInit = {}) {
  const csrfToken = getCookie('csrf_token');
  
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };
  
  // Add CSRF for mutating methods
  const method = (options.method || 'GET').toUpperCase();
  if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
    if (csrfToken) headers['X-CSRF-Token'] = csrfToken;
  }
  
  // Add auth if available
  const accessToken = getAccessToken(); // From memory/storage
  if (accessToken) headers['Authorization'] = `Bearer ${accessToken}`;
  
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
    credentials: 'include', // Important: sends cookies
  });
  
  if (response.status === 401) {
    // Try refresh
    await refreshToken();
    return apiFetch(path, options); // Retry once
  }
  
  return response;
}

async function refreshToken() {
  const response = await fetch(`${API_BASE}/auth/refresh`, {
    method: 'POST',
    credentials: 'include',
  });
  if (response.ok) {
    const data = await response.json();
    storeAccessToken(data.access_token);
  } else {
    // Redirect to login
    window.location.href = '/login';
  }
}
```

### React Hook Example

```tsx
function useAuth() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  
  useEffect(() => {
    checkAuth();
  }, []);
  
  async function checkAuth() {
    try {
      const res = await apiFetch('/auth/me');
      if (res.ok) {
        const data = await res.json();
        setUser(data);
      }
    } catch {
      // Not authenticated
    } finally {
      setLoading(false);
    }
  }
  
  async function login(email: string, password: string) {
    const res = await apiFetch('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
    if (res.ok) {
      const data = await res.json();
      setUser(data.user);
      return data;
    }
    throw new Error('Login failed');
  }
  
  async function logout(allDevices = false) {
    await apiFetch('/auth/logout', {
      method: 'POST',
      body: JSON.stringify({ all_devices: allDevices }),
    });
    setUser(null);
  }
  
  return { user, loading, login, logout, checkAuth };
}
```

## Common Issues

### "CSRF validation failed"
- Ensure `X-CSRF-Token` header is sent
- Ensure `csrf_token` cookie exists
- Check `credentials: 'include'` in fetch

### "No refresh token"
- Cookie may be blocked (check `Secure`, `SameSite`)
- Ensure `credentials: 'include'` on all requests
- Check domain/path match

### "Too many requests"
- Respect rate limits
- Implement exponential backoff
- Cache responses where appropriate

### Token Expired Errors
- Implement proactive refresh (at 50-75% TTL)
- Handle 401 → refresh → retry pattern
- Clear tokens on repeated 401 after refresh