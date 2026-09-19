# Authentication Security

## JWT Implementation

### Token Structure

#### Access Token (15 min)
```json
{
  "sub": "user-uuid",
  "exp": 1705315800,
  "jti": "a1b2c3d4e5f6...",
  "type": "access"
}
```

#### Refresh Token (7 days)
```json
{
  "sub": "user-uuid",
  "exp": 1705834200,
  "jti": "f6e5d4c3b2a1...",
  "type": "refresh"
}
```

#### Email Verification (24 hours)
```json
{
  "sub": "user-uuid",
  "exp": 1705402200,
  "type": "email_verify"
}
```

#### Password Reset (1 hour)
```json
{
  "sub": "user-uuid",
  "exp": 1705319400,
  "type": "password_reset"
}
```

### Signing Algorithm
- **Algorithm**: HS256 (configurable via `JWT_ALGORITHM`)
- **Secret**: `JWT_SECRET` (min 64 chars, rotated periodically)
- **Key ID**: Not used (single key), `jti` provides uniqueness

### Token Validation

```python
def decode_token(token: str) -> dict:
    return jwt.decode(
        token,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
        options={
            "verify_signature": True,
            "verify_exp": True,
            "verify_aud": False,  # No audience claim
            "verify_iss": False   # No issuer claim
        }
    )
```

### Claims Verification
- `exp` - Expiration (required)
- `sub` - Subject/user ID (required)
- `jti` - Unique token ID (required, for revocation)
- `type` - Token type (access/refresh/email_verify/password_reset)

## Password Security

### Hashing
- **Algorithm**: bcrypt
- **Cost Factor**: 12 rounds
- **Salt**: Generated per password (bcrypt.gensalt)

```python
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())
```

### Password Policy
- Minimum 8 characters
- Maximum 128 characters (bcrypt limit)
- No common password list check (recommended to add)
- Breach check via HaveIBeenPwned API (recommended)

### Storage
- Only bcrypt hash stored
- Never log passwords or hashes
- Timing-safe comparison via bcrypt.checkpw

## Session Management

### Refresh Token Rotation

```
Login
  │
  ├─▶ Access Token (15m) ──▶ Response body
  │
  └─▶ Refresh Token (7d) ──▶ HTTP-only cookie
       │
       ├─▶ POST /auth/refresh
       │      │
       │      ├─▶ Validate refresh token
       │      ├─▶ Check not revoked (Redis blacklist)
       │      ├─▶ Check not expired
       │      ├─▶ Invalidate old refresh token (blacklist)
       │      ├─▶ Generate new access + refresh tokens
       │      ├─▶ Set new refresh cookie
       │      ├─▶ Set new CSRF cookie
       │      └─▶ Return new access token
       │
       └─▶ Logout / Revoke
              │
              ├─▶ Blacklist refresh token (Redis)
              ├─▶ Delete cookies
              └─▶ (Optional) Blacklist access token
```

### Token Blacklisting

```python
# Redis key: "blacklist:refresh:{jti}" → "1" (TTL = token remaining time)
# Redis key: "blacklist:access:{jti}" → "1" (TTL = token remaining time)

async def is_token_revoked(jti: str, token_type: str) -> bool:
    key = f"blacklist:{token_type}:{jti}"
    return await redis.exists(key)
```

### Session Tracking

```python
# Database table: refresh_tokens
# - id (uuid)
# - user_id (fk)
# - token_hash (sha256)
# - user_agent
# - ip
# - created_at
# - expires_at
# - revoked_at (nullable)
# - revoked_reason (logout, rotation, admin, security)
```

### Device Fingerprinting

```python
def create_token_fingerprint(user_agent: str, ip: str) -> str:
    raw = f"{user_agent}:{ip}"
    return hashlib.sha256(raw.encode()).hexdigest()
```

Used for:
- Anomaly detection (new device alerts)
- Session listing (`/auth/sessions`)
- Concurrent session limits (future)

## CSRF Protection

### Double-Submit Cookie Pattern

1. Server generates cryptographically random token (32 bytes hex)
2. Set in `csrf_token` cookie (accessible to JS, `HttpOnly=false`)
3. Client reads cookie, sends in `X-CSRF-Token` header
4. Server validates header === cookie

```python
def generate_csrf_token() -> str:
    return secrets.token_hex(32)
```

### Cookie Configuration

```python
response.set_cookie(
    key=settings.CSRF_COOKIE_NAME,  # "csrf_token"
    value=csrf_token,
    httponly=False,   # JS needs to read it
    secure=True,      # HTTPS only
    samesite="lax",   # CSRF protection + top-level nav
    max_age=settings.REFRESH_COOKIE_MAX_AGE,  # 7 days
    path="/"
)
```

### Exempt Paths

No CSRF required for:
- `GET`, `HEAD`, `OPTIONS`
- Auth endpoints (login, signup, refresh, password reset)
- Email OTP endpoints
- Webhook endpoints (platform-initiated)
- Health checks

## Rate Limiting on Auth

### Limits

| Endpoint | Limit | Window | Scope |
|----------|-------|--------|-------|
| Signup | 5 | 60s | IP |
| Login | 10 | 60s | IP |
| Login | 10 | 60s | User (email) |
| Refresh | 30 | 60s | IP |
| Forgot Password | 3 | 60s | IP |
| Reset Password | 3 | 60s | IP |
| Verify OTP | 10 | 60s | IP |

### Implementation

```python
async def rate_limit(key: str, limit: int, window_seconds: int) -> bool:
    # Redis sorted set: key → {timestamp: score}
    # Remove expired entries
    # Count current window
    # If under limit: add current timestamp, return True
    # Else: return False
```

### Fail-Closed Behavior

```python
AUTH_RATE_LIMIT_FAIL_CLOSED = True  # Default

# When Redis unavailable:
if settings.AUTH_RATE_LIMIT_FAIL_CLOSED:
    raise HTTPException(503, "Rate limit service unavailable")
else:
    return True  # Allow (dev only)
```

### Trusted Proxy IP Detection

```python
def get_client_ip(request: Request) -> str:
    peer = request.client.host
    if not _ip_in_trusted_proxy(peer):
        return peer  # Direct connection - trust socket IP
    
    # Behind trusted proxy - use rightmost XFF
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[-1].strip()
    return request.headers.get("x-real-ip", peer)
```

## Account Lockout

### Policy
- **Max Failed Attempts**: 5
- **Lockout Duration**: 15 minutes
- **Scope**: Per IP + Per user identity

### Implementation

```python
# Table: login_attempts
# - id
# - identifier (email or IP)
# - attempt_type (login, signup, etc.)
# - success (boolean)
# - created_at

# Cleanup: Retention job runs every 6 hours, deletes > 30 days
```

### Unlock
- Automatic after 15 minutes
- Manual via admin (future)
- Successful login clears attempts for that identity

## OAuth Flows

### Google Reviews OAuth

```
User clicks "Connect Google"
    │
    ▼
GET /api/v1/channels/google/connect?token=ACCESS_TOKEN
    │
    ├─▶ Validate access token (or query param token)
    ├─▶ Generate signed state JWT (10 min, binds user_id)
    ├─▶ Build Google OAuth URL with state
    └─▶ Redirect to Google
           │
           ▼
User authorizes on Google
           │
           ▼
Google redirects to /api/v1/channels/google/callback?code=...&state=...
           │
           ├─▶ Verify state JWT (valid, not expired, correct type)
           ├─▶ Exchange code for tokens
           ├─▶ List Google Business accounts
           ├─▶ For each location: create Channel record
           │      ├─▶ Encrypt access/refresh tokens
           │      ├─▶ Store location_id in metadata
           │      └─▶ Set webhook_secret
           └─▶ Redirect to frontend with success
```

### State Token

```python
def _google_oauth_state(user_id: str, next_path: str | None = None) -> str:
    payload = {
        "sub": user_id,
        "type": "google_oauth",
        "jti": secrets.token_hex(8),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
    }
    if next_path:
        payload["next"] = next_path
    return pyjwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
```

## Email Verification

### Flow

```
Signup
    │
    ├─▶ Create user (email_verified=false)
    ├─▶ Generate email_verify JWT (24h)
    ├─▶ Send email with link: /verify-email?token=...
    └─▶ Return verification_token in response (dev)
         │
         ▼
User clicks link / POST /api/v1/auth/verify-email
    │
    ├─▶ Decode token
    ├─▶ Verify type=email_verify, not expired
    ├─▶ Find user by sub
    ├─▶ Set email_verified=true
    └─▶ Return success
```

### OTP Alternative

```
POST /api/v1/auth/verify-otp
    │
    ├─▶ Rate limit (10/min per IP)
    ├─▶ Verify code matches stored OTP (Redis, 10 min TTL)
    ├─▶ Set email_verified=true
    ├─▶ Issue access + refresh tokens
    └─▶ Return tokens
```

## Password Reset

### Flow

```
POST /api/v1/auth/forgot-password
    │
    ├─▶ Rate limit (3/min per IP)
    ├─▶ Find user by email (constant-time)
    ├─▶ Generate password_reset JWT (1h)
    ├─▶ Store reset token hash in DB (optional)
    ├─▶ Send email with link: /reset-password?token=...
    └─▶ Return generic success (no enumeration)
         │
         ▼
POST /api/v1/auth/reset-password
    │
    ├─▶ Rate limit (3/min per IP)
    ├─▶ Decode token, verify type=password_reset
    ├─▶ Find user by sub
    ├─▶ Validate new password strength
    ├─▶ Hash new password
    ├─▶ Revoke all refresh tokens for user
    └─▶ Return success
```

## Security Headers

### Response Headers (via middleware)

```python
# Added by FastAPI/Starlette middleware
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
Referrer-Policy: strict-origin-when-cross-origin
Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; connect-src 'self' https:; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'
Permissions-Policy: accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()
```

### CORS Configuration

```python
CORS_ORIGINS = ["http://localhost:3000"]  # Configurable
ALLOW_CREDENTIALS = True
ALLOW_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH"]
ALLOW_HEADERS = ["Content-Type", "Authorization", "X-CSRF-Token"]
EXPOSE_HEADERS = ["X-CSRF-Token"]
```

## Vulnerabilities Addressed

| CWE | Vulnerability | Mitigation |
|-----|---------------|------------|
| CWE-287 | Improper Authentication | JWT with exp, jti, rotation |
| CWE-384 | Session Fixation | New tokens on login/refresh |
| CWE-613 | Insufficient Session Expiration | 15m access, 7d refresh, rotation |
| CWE-352 | CSRF | Double-submit cookie |
| CWE-79 | XSS | HttpOnly cookies, CSP, encoding |
| CWE-200 | Information Exposure | Generic error messages |
| CWE-307 | Improper Restriction of Excessive Authentication Attempts | Rate limiting, lockout |
| CWE-522 | Insufficiently Protected Credentials | bcrypt cost 12, HTTPS only |
| CWE-640 | Weak Password Recovery | Time-limited tokens, rate limits |
| CWE-295 | Improper Certificate Validation | TLS enforcement, cert pinning (planned) |

## Testing Checklist

- [ ] Access token expires in 15 minutes
- [ ] Refresh token rotates on use
- [ ] Old refresh token invalidated after rotation
- [ ] Refresh token expires in 7 days
- [ ] Logout revokes refresh token
- [ ] All-devices logout revokes all sessions
- [ ] CSRF required on POST/PUT/PATCH/DELETE
- [ ] CSRF exempt on auth endpoints
- [ ] CSRF token in cookie matches header
- [ ] Rate limits enforced on auth endpoints
- [ ] Fail-closed when Redis down
- [ ] Passwords hashed with bcrypt cost 12
- [ ] No password in logs
- [ ] Email enumeration prevented
- [ ] OAuth state validated
- [ ] Webhook signatures verified