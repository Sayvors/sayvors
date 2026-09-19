# API Security

## Input Validation

### Pydantic Models

All API inputs validated via Pydantic schemas:

```python
# Example: schemas.py
class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    
    @field_validator('password')
    @classmethod
    def password_complexity(cls, v):
        # Optional: enforce complexity
        if not re.search(r'[A-Z]', v):
            raise ValueError('Password must contain uppercase')
        if not re.search(r'[a-z]', v):
            raise ValueError('Password must contain lowercase')
        if not re.search(r'\d', v):
            raise ValueError('Password must contain digit')
        return v

class PostCreate(BaseModel):
    listing_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    content: str = Field(min_length=1, max_length=5000)
    media_urls: list[HttpUrl] = Field(default=[], max_length=10)
    publish_at: datetime | None = None
    status: Literal["draft", "scheduled", "published"] = "published"
```

### Validation Layers

1. **Pydantic** - Request body parsing & validation
2. **FastAPI** - Path/query parameter validation
3. **Service Layer** - Business logic validation
4. **Database** - Constraints (FK, unique, not null)

### Sanitization

```python
# HTML sanitization for user content
import bleach

def sanitize_html(content: str) -> str:
    return bleach.clean(
        content,
        tags=['b', 'i', 'u', 'em', 'strong', 'p', 'br'],
        attributes={},
        strip=True
    )

# SQL injection prevention - ALWAYS use parameterized queries
# SQLAlchemy ORM handles this automatically
result = await db.execute(
    select(User).where(User.email == email)  # Parameterized
)
```

## Output Encoding

### JSON Responses

FastAPI/Pydantic automatically JSON-encodes responses. No manual encoding needed.

### HTML Contexts (if any)

```python
# If rendering templates (not used in API)
from markupsafe import escape
safe_content = escape(user_input)
```

## Security Headers

### Implemented Headers

```python
# Via Starlette middleware or nginx
Strict-Transport-Security: max-age=31536000; includeSubDomains; preload
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
Referrer-Policy: strict-origin-when-cross-origin
Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; connect-src 'self' https:; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'
Permissions-Policy: accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Resource-Policy: same-origin
Cross-Origin-Embedder-Policy: require-corp
```

### CSP Details

| Directive | Value | Reason |
|-----------|-------|--------|
| default-src | 'self' | Restrict all by default |
| script-src | 'self' | No inline scripts |
| style-src | 'self' 'unsafe-inline' | Allow inline styles for components |
| img-src | 'self' data: https: | Images from self, data URIs, HTTPS |
| connect-src | 'self' https: | API calls to self and HTTPS |
| font-src | 'self' | Fonts from self |
| frame-ancestors | 'none' | Prevent clickjacking |
| base-uri | 'self' | Prevent base tag injection |
| form-action | 'self' | Forms only to self |

## CORS Configuration

```python
CORS_ORIGINS = [
    "http://localhost:3000",      # Dev
    "https://app.sayvors.com",    # Prod
    "https://staging.sayvors.com" # Staging
]

ALLOW_CREDENTIALS = True
ALLOW_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]
ALLOW_HEADERS = ["Content-Type", "Authorization", "X-CSRF-Token", "Idempotency-Key"]
EXPOSE_HEADERS = ["X-CSRF-Token", "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"]
MAX_AGE = 86400  # 24 hours
```

## Request Size Limits

```python
# FastAPI default: 1MB for JSON
# Configured per endpoint for webhooks

MAX_WEBHOOK_BODY_BYTES = 1_000_000  # 1 MB

@router.post("/webhook/{platform}")
async def webhook(request: Request):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_WEBHOOK_BODY_BYTES:
        return Response(status_code=413, content="Payload too large")
    
    raw_body = await request.body()
    if len(raw_body) > MAX_WEBHOOK_BODY_BYTES:
        return Response(status_code=413, content="Payload too large")
```

### Upload Limits

```python
MAX_UPLOAD_SIZE_MB = 100  # Configurable

# Enforced at nginx level too:
# client_max_body_size 100M;
```

## Rate Limiting

### Multi-Layer Approach

| Layer | Scope | Implementation |
|-------|-------|----------------|
| WAF/Cloudflare | IP, Geo, Bot | Cloudflare rules |
| Nginx | IP, Burst | `limit_req_zone` |
| Application (Redis) | User, Endpoint | Sliding window |
| Auth-specific | IP, User | Custom middleware |

### Application Rate Limiter

```python
# services/api/app/modules/auth/rate_limit.py

async def rate_limit(key: str, limit: int, window_seconds: int) -> bool:
    """
    Sliding window rate limit using Redis sorted sets.
    Key format: "ratelimit:{scope}:{identifier}"
    """
    now = time.time()
    window_start = now - window_seconds
    
    # Redis pipeline for atomicity
    pipe = redis.pipeline()
    pipe.zremrangebyscore(key, 0, window_start)  # Remove expired
    pipe.zcard(key)  # Count current
    pipe.zadd(key, {str(now): now})  # Add current
    pipe.expire(key, window_seconds + 1)  # TTL
    results = await pipe.execute()
    
    current_count = results[1]
    if current_count >= limit:
        # Remove the one we just added
        await redis.zrem(key, str(now))
        return False
    
    return True
```

### Rate Limit Headers

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1705315800
Retry-After: 45  # On 429
```

## API Versioning

### URL Versioning

```
/api/v1/locations/
/api/v1/posts/
/api/v2/locations/  # Future breaking changes
```

### Deprecation Policy

1. Announce deprecation 3 months in advance
2. Add `Deprecation: true` header
3. Add `Sunset` header with date
4. Maintain old version during transition
5. Remove after sunset date

```python
@router.get("/v1/old-endpoint", deprecated=True)
async def old_endpoint():
    # Add deprecation headers
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "Sat, 01 Jan 2025 00:00:00 GMT"
    response.headers["Link"] = '</api/v2/new-endpoint>; rel="successor-version"'
    ...
```

## IDOR Prevention

### Pattern: Always Filter by Owner

```python
# ❌ BAD - No ownership check
@router.get("/posts/{post_id}")
async def get_post(post_id: str, db: AsyncSession = Depends(get_db)):
    return await db.get(Post, post_id)

# ✅ GOOD - Ownership enforced
@router.get("/posts/{post_id}")
async def get_post(
    post_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    post = await service.get_post(db, user.id, post_id)
    if not post:
        raise HTTPException(404, "Post not found")
    return post

# Service layer
async def get_post(db: AsyncSession, user_id: str, post_id: str):
    result = await db.execute(
        select(Post).where(Post.id == post_id, Post.user_id == user_id)
    )
    return result.scalar_one_or_none()
```

### Testing IDOR

```python
async def test_idor_prevented(client, user1, user2, post1):
    # User1 creates post
    # User2 tries to access
    response = await client.get(
        f"/api/v1/posts/{post1.id}",
        headers=auth_headers(user2)
    )
    assert response.status_code == 404  # Not 403 (prevents enumeration)
```

## Mass Assignment Prevention

### Explicit Field Allowlisting

```python
@router.patch("/me")
async def update_me(
    body: dict,  # Raw dict, not Pydantic model
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Explicitly allow only safe fields
    allowed_fields = {"onboarded", "first_name", "last_name", "theme", "language"}
    update_data = {k: v for k, v in body.items() if k in allowed_fields}
    
    if not update_data:
        raise HTTPException(400, "No valid fields to update")
    
    for field, value in update_data.items():
        setattr(user, field, value)
    db.add(user)
    await db.commit()
    return {"message": "Updated"}
```

### Pydantic Model with Extra Forbidden

```python
class UserUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')  # Reject unknown fields
    
    first_name: str | None = Field(None, max_length=100)
    last_name: str | None = Field(None, max_length=100)
    theme: Literal["light", "dark", "system"] | None = None
    language: str | None = Field(None, pattern=r'^[a-z]{2}$')
```

## Webhook Security

### Signature Verification

All incoming webhooks verified via HMAC:

```python
_SIGNATURE_HEADERS = {
    "facebook": "x-hub-signature-256",
    "instagram": "x-hub-signature-256",
    "x": "x-twitter-webhooks-signature",
    "telegram": "x-telegram-bot-api-secret-token",
    "whatsapp": "x-hub-signature-256",
    "linkedin": "x-linkedin-signature",
}

async def verify_webhook(platform: str, body: bytes, signature: str, channel: Channel) -> bool:
    secret = channel.webhook_secret
    if not secret:
        return False
    
    if platform in ["facebook", "instagram", "whatsapp"]:
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)
    # ... other platforms
```

### Replay Protection

- Timestamp in payload validated (within 5 min)
- Event ID deduplication (Redis set with TTL)
- Idempotency keys for outgoing webhooks

## Error Information Leakage

### Generic Error Messages

```python
# ❌ BAD - Leaks information
raise HTTPException(404, f"User with email {email} not found")

# ✅ GOOD - Generic
raise HTTPException(404, "Resource not found")
raise HTTPException(401, "Invalid credentials")  # Not "user not found" vs "wrong password"
```

### Debug Info in Development Only

```python
if settings.ENVIRONMENT == "development":
    raise HTTPException(500, f"Internal error: {str(e)}")
else:
    logger.error("Internal error", exc_info=e)
    raise HTTPException(500, "Internal server error")
```

## Security Testing Checklist

### Automated (CI)

- [ ] Dependency scan (`pip-audit`)
- [ ] SAST (`bandit`)
- [ ] Secret scan (`detect-secrets`)
- [ ] Container scan (`trivy`)
- [ ] License compliance

### Manual (Per Release)

- [ ] Authentication bypass attempts
- [ ] Authorization/IDOR testing
- [ ] Input validation fuzzing
- [ ] Rate limit testing
- [ ] CSRF testing
- [ ] Webhook signature validation
- [ ] Error message review
- [ ] Security header verification
- [ ] CORS policy review
- [ ] API versioning/deprecation

### Penetration Testing

- Annual third-party assessment
- Scope: All API endpoints, auth flows, webhooks
- Retest after critical findings fixed