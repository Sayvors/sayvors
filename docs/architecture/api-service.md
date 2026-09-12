# API Service (FastAPI) Internals

## Application Structure

```
services/api/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app, lifespan, middleware
│   ├── config.py            # Pydantic Settings
│   ├── security.py          # JWT, passwords, tokens
│   ├── database.py          # SQLAlchemy engine, session
│   ├── core/
│   │   ├── __init__.py
│   │   ├── deps.py          # FastAPI dependencies
│   │   ├── http.py          # HTTP client (httpx)
│   │   └── pinned_http.py   # Pinned connections for external APIs
│   └── modules/
│       ├── auth/
│       ├── locations/
│       ├── posts/
│       ├── analytics/
│       ├── channels/
│       ├── llm/
│       ├── profile/
│       ├── localith/
│       ├── tts/
│       ├── stt/
│       ├── rag/
│       ├── email/
│       ├── kafka/
│       ├── redis/
│       ├── outbox/
│       └── webhooks/        # (in channels/router.py)
├── alembic/                 # Migrations
├── tests/
├── scripts/
├── pyproject.toml
└── Dockerfile
```

## Main Application (`main.py`)

### Lifespan Events
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    1. Warm DB connection pool
    2. Connect Redis (mark unavailable on failure)
    3. Connect Kafka (mark unavailable on failure, 5s timeout)
    4. Run retention cleanup (login_attempts, refresh_tokens)
    5. Start background tasks:
       - Retention cleanup loop (6h interval)
       - Google Reviews poll worker (5m interval)
       - Localith sync worker (1m interval)
       - Posts publish worker (5m interval)
       - Analytics consumer (Kafka)
       - Performance sync worker (6h interval)
       - Outbox worker
    yield
    # Shutdown
    6. Cancel all background tasks
    7. Flush Kafka producer
    8. Close Redis/Kafka connections
```

### Middleware Stack (Order Matters)
```python
app.add_middleware(CORSMiddleware, ...)           # 1. CORS
app.add_middleware(CSRFMiddleware)                # 2. CSRF (after CORS)
if settings.ALLOWED_HOSTS:
    app.add_middleware(TrustedHostMiddleware, ...) # 3. Host validation
```

### CSRF Middleware
```python
class CSRFMiddleware(BaseHTTPMiddleware):
    # Exempt: GET/HEAD/OPTIONS, auth endpoints, webhooks, health
    # Validate: X-CSRF-Token header == csrf_token cookie
    # Return 403 on mismatch
```

## Configuration (`config.py`)

### Settings Class (Pydantic BaseSettings)
```python
class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/sayvors"
    DB_POOL_SIZE: int = 10
    DB_POOL_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT_SECONDS: int = 30
    
    # Auth
    JWT_SECRET: str = "change-me-in-production"  # Fatal if default
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_EXPIRATION_MINUTES: int = 15
    JWT_REFRESH_EXPIRATION_DAYS: int = 7
    
    # Security
    MAX_LOGIN_ATTEMPTS: int = 5
    LOCKOUT_MINUTES: int = 15
    AUTH_RATE_LIMIT_FAIL_CLOSED: bool = True
    TRUSTED_PROXIES: list[str] = ["127.0.0.1", "::1"]
    CSRF_COOKIE_NAME: str = "csrf_token"
    REFRESH_COOKIE_NAME: str = "refresh_token"
    ALLOWED_HOSTS: list[str] = ["localhost", "127.0.0.1"]
    
    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]
    
    # External
    REDIS_URL: str = "redis://localhost:6379/0"
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    
    # File uploads
    UPLOAD_DIR: str = "./data/uploads"
    MAX_UPLOAD_SIZE_MB: int = 100
    
    # Encryption
    CHANNEL_ENCRYPTION_KEY: str = ""  # Falls back to JWT_SECRET
    
    # Email (Resend)
    RESEND_API_KEY: str = ""
    RESEND_FROM: str = "Sayvors <noreply@sayvors.com>"
    FRONTEND_URL: str = "http://localhost:3000"
    
    # Google Business
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REVIEWS_REDIRECT_URI: str = "http://localhost:8000/api/v1/channels/google/callback"
    GOOGLE_REVIEWS_MOCK: bool = False
    GOOGLE_REVIEWS_POLL_INTERVAL_SECONDS: int = 300
    
    # Localith
    LOCALITH_API_KEY: str = ""
    LOCALITH_SYNC_INTERVAL_SECONDS: int = 100
    
    # Analytics
    ANALYTICS_PERFORMANCE_SYNC_INTERVAL_SECONDS: int = 6 * 3600
    ANALYTICS_PERFORMANCE_DAYS_BACK: int = 30
    DEMO_MODE: bool = False
    
    # LLM Keys
    OPENAI_API_KEY: str = ""
    XAI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    # ... more
    
    model_config = {"env_file": ".env"}
```

### Validation
```python
if settings.JWT_SECRET == "change-me-in-production":
    sys.exit(1)  # Hard fail on startup
```

## Database (`database.py`)

### Engine & Session
```python
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_POOL_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT_SECONDS,
    pool_pre_ping=True,
    echo=False,
)

async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
```

### Dependencies
```python
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session
```

## Core Dependencies (`core/deps.py`)

### Authentication
```python
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    # 1. Decode JWT
    # 2. Check access token blacklist (Redis)
    # 3. Fetch user from DB
    # 4. Return User model
```

### Rate Limiting
```python
async def rate_limit(key: str, limit: int, window_seconds: int) -> bool:
    # Redis sorted set sliding window
    # Key: "ratelimit:{key}"
    # Returns True if allowed, False if limited
```

### Redis Client (`modules/redis/client.py`)
```python
# Global state
_redis: Redis | None = None
_redis_unavailable = False

async def get_redis() -> Redis:
    global _redis, _redis_unavailable
    if _redis_unavailable:
        raise RuntimeError("Redis unavailable")
    if _redis is None:
        _redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis

def mark_redis_unavailable():
    global _redis_unavailable
    _redis_unavailable = True
```

### Kafka Client (`modules/kafka/client.py`)
```python
# Similar pattern - global producer, mark_unavailable on failure
async def get_kafka_producer() -> AIOKafkaProducer:
    ...

def mark_kafka_unavailable():
    ...
```

## Security Module (`security.py`)

### Password Hashing
```python
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())
```

### JWT Tokens
```python
def create_access_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_ACCESS_EXPIRATION_MINUTES)
    jti = secrets.token_hex(16)
    return jwt.encode(
        {"sub": subject, "exp": expire, "jti": jti, "type": "access"},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )

def create_refresh_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_EXPIRATION_DAYS)
    jti = secrets.token_hex(16)
    return jwt.encode(
        {"sub": subject, "exp": expire, "jti": jti, "type": "refresh"},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
```

### Token Decoding
```python
def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
```

### Token Hashing (for storage)
```python
def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
```

### Other Tokens
```python
def generate_verification_token() -> str:  # Email verification
    return secrets.token_urlsafe(32)

def generate_csrf_token() -> str:
    return secrets.token_hex(32)

def create_email_verification_token(user_id: str) -> str:  # JWT, 24h
    ...

def create_password_reset_token(user_id: str) -> str:  # JWT, 1h
    ...

def create_token_fingerprint(user_agent: str, ip: str) -> str:
    return hashlib.sha256(f"{user_agent}:{ip}".encode()).hexdigest()
```

## Module Router Pattern

### Standard Router Structure
```python
# modules/auth/router.py
from fastapi import APIRouter, Depends, HTTPException, ...

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

@router.post("/login")
async def login_endpoint(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    # 1. Rate limit
    # 2. Call service
    # 3. Set cookies (refresh_token, csrf_token)
    # 4. Return access_token + user
```

### Service Layer Pattern
```python
# modules/auth/service.py
async def login(body: LoginRequest, db: AsyncSession, user_agent: str, ip: str):
    # 1. Find user by email
    # 2. Verify password
    # 3. Check email_verified
    # 4. Create access + refresh tokens
    # 5. Store refresh token hash in DB
    # 6. Return tokens + user
```

## Background Workers

### Started in Lifespan
```python
# All started as asyncio tasks
retention_task = asyncio.create_task(run_retention_loop())
reviews_task = asyncio.create_task(run_google_reviews_worker())
localith_sync_task = asyncio.create_task(run_localith_sync_worker())
posts_publish_task = asyncio.create_task(run_post_publish_worker())
analytics_consumer_task = asyncio.create_task(run_analytics_consumer())
performance_sync_task = asyncio.create_task(run_performance_sync_worker())
outbox_worker = OutboxWorker()
await outbox_worker.start()
```

### Worker Pattern
```python
# modules/analytics/consumer.py
async def run_analytics_consumer():
    consumer = AIOKafkaConsumer(
        "review-events",
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id="analytics-consumer",
        auto_offset_reset="latest",
    )
    await consumer.start()
    try:
        async for msg in consumer:
            await process_review_event(json.loads(msg.value))
    finally:
        await consumer.stop()
```

### Outbox Worker
```python
# modules/outbox/worker.py
class OutboxWorker:
    async def start(self):
        self._task = asyncio.create_task(self._run())
    
    async def _run(self):
        while True:
            events = await fetch_pending_events(db, batch_size=100)
            for event in events:
                await publish_to_kafka(event)
                await mark_event_published(db, event.id)
            await asyncio.sleep(1)
```

## Error Handling

### HTTP Exceptions
```python
# Standard pattern
try:
    result = await service.do_something(db, user_id, data)
except ValueError as e:
    raise HTTPException(status_code=400, detail=str(e))
except RuntimeError as e:
    raise HTTPException(status_code=502, detail=str(e))  # External API failure
```

### Global Exception Handlers (Not Implemented)
- No custom exception handlers
- FastAPI default 500 for unhandled exceptions
- Sentry captures if configured

## Testing

### Test Structure
```
tests/
├── conftest.py          # Fixtures: db, client, auth_headers
├── test_api.py          # Basic endpoint tests
├── test_auth.py         # Auth flow tests
├── test_locations.py
├── test_posts.py
├── test_analytics.py
├── test_channels.py
├── test_llm.py
└── ...
```

### Fixtures (conftest.py)
```python
@pytest.fixture
async def db():
    # Creates test database, runs migrations
    yield session
    # Cleanup

@pytest.fixture
def client(db):
    # TestClient with dependency overrides
    yield TestClient(app)

@pytest.fixture
def auth_headers(user):
    # Returns headers with valid access token
    return {"Authorization": f"Bearer {access_token}"}
```

## Performance Considerations

### Connection Pooling
- DB: 10 + 10 overflow, 30s timeout
- Redis: Single connection (global)
- HTTP: httpx.AsyncClient with limits

### Query Optimization
- `selectinload` for relationships
- Indexed columns: `user_id`, `channel_id`, `listing_id`
- Pagination with `limit`/`offset`

### Caching
- Redis used for: rate limits, sessions, OTP tokens
- No application-level caching yet

## Known Issues

1. **Workers in lifespan** - Coupled to API process, can't scale independently
2. **No graceful shutdown** - Tasks cancelled abruptly
3. **Single Kafka consumer group** - No parallelism
4. **Blocking Redis calls** - Some sync calls in async context
5. **No request timeout** - Long requests can hang
6. **No circuit breakers** - External API failures cascade