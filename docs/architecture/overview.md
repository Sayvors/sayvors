# System Architecture Overview

## High-Level Components

```
┌─────────────────────────────────────────────────────────────────────────────┐
                              SAYVORS PLATFORM                                  
└─────────────────────────────────────────────────────────────────────────────┘

┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   Web App    │    │  Admin App   │    │  Landing     │    │   Mobile     │
│  (Next.js)   │    │  (Next.js)   │    │  (Static)    │    │  (Future)    │
└──────┬───────┘    └──────┬───────┘    └──────┬───────┘    └──────┬───────┘
       │                   │                   │                   │
       └───────────────────┼───────────────────┼───────────────────┘
                           │                   │
                           ▼                   ▼
              ┌────────────────────────────────────────────────┐
              │              API GATEWAY (nginx)                │
              │         TLS Termination, CORS, Rate Limit      │
              └────────────────────┬───────────────────────────┘
                                   │
                                   ▼
              ┌────────────────────────────────────────────────┐
              │            SAYVORS API (FastAPI)                │
              │  ┌──────────────────────────────────────────┐   │
              │  │              MODULES                      │   │
              │  │  auth  locations  posts  analytics       │   │
              │  │  channels  llm  profile  localith        │   │
              │  │  tts  stt  rag  email  kafka  redis      │   │
              │  │  outbox  webhooks                         │   │
              │  └──────────────────────────────────────────┘   │
              └────────┬────────────────────┬──────────────────┘
                       │                    │
        ┌──────────────┼──────────────┐     │     ┌─────────────────┐
        ▼              ▼              ▼     ▼     ▼                 ▼
┌──────────────┐ ┌───────────┐ ┌──────────┐ ┌────────┐ ┌─────────────────────┐
│ PostgreSQL   │ │  Redis    │ │  Kafka   │ │ S3/    │ │  EXTERNAL APIs      │
│ (Primary DB) │ │ (Cache,   │ │ (Events, │ │ Local  │ │  Google Business    │
│              │ │  Sessions,│ │  Async)  │ │ Files  │ │  Profile API        │
│              │ │  Rate Lim)│ │          │ │        │ │  EmbedSocial        │
└──────────────┘ └───────────┘ └──────────┘ └────────┘ │  LLM Providers      │
                                                      │  (Groq, OpenAI,     │
                                                      │   Gemini, etc.)     │
                                                      │  Resend (Email)     │
                                                      └─────────────────────┘
```

## Service Boundaries

| Service | Responsibility | Technology |
|---------|---------------|------------|
| **API** | Core business logic, REST API, auth | FastAPI, Python 3.12 |
| **Web App** | Customer dashboard | Next.js 14, React 18, TypeScript |
| **Admin App** | Internal tooling | Next.js 14 (planned) |
| **PostgreSQL** | Persistent storage | PostgreSQL 16, asyncpg |
| **Redis** | Caching, sessions, rate limiting | Redis 7 |
| **Kafka** | Event streaming, async processing | Apache Kafka 3.x |

## Data Flow

### Request Flow (Synchronous)

```
Client → nginx → FastAPI → PostgreSQL
                ↓
           Redis (cache/rate limit)
                ↓
           Response → Client
```

### Async Flow (Event-Driven)

```
API Request → PostgreSQL (transaction) → Outbox Table
                                    ↓
                              Outbox Worker (polling)
                                    ↓
                              Kafka Topics
                                    ↓
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
             Analytics         Notifications    External Sync
             Consumer          (Email, Push)    (Google, etc.)
```

## Module Architecture (FastAPI)

### Module Structure
```
services/api/app/modules/
├── auth/           # Authentication, sessions, passwords
├── locations/      # Business locations (Google + Localith)
├── posts/          # Google Business posts (create, schedule, publish)
├── analytics/      # Reviews, insights, intelligence, benchmarks
├── channels/       # Multi-platform channels (Google, FB, Insta, etc.)
├── llm/            # LLM conversations, chat, streaming
├── profile/        # User profile, databanks, settings
├── localith/       # EmbedSocial integration (listings, reviews, metrics)
├── tts/            # Text-to-speech
├── stt/            # Speech-to-text
├── rag/            # Retrieval-Augmented Generation
├── email/          # OTP emails via Resend
├── kafka/          # Kafka producer/client
├── redis/          # Redis client, caching
├── outbox/         # Transactional outbox pattern
└── webhooks/       # Incoming webhook handlers (in channels/)
```

### Module Pattern
Each module follows:
```
module/
├── __init__.py
├── router.py       # FastAPI routes (thin)
├── service.py      # Business logic
├── models.py       # SQLAlchemy models
├── schemas.py      # Pydantic schemas
└── worker.py       # Background workers (if needed)
```

## Key Design Patterns

### 1. Transactional Outbox
```python
# In service: write to DB + outbox in same transaction
async def create_post(db, user_id, data):
    post = Post(...)
    db.add(post)
    await db.flush()
    
    await enqueue_event("post.created", {"post_id": post.id}, "post-events")
    await db.commit()
```

### 2. Background Workers (Async)
```python
# Lifespan starts workers
async def run_analytics_consumer():
    consumer = AIOKafkaConsumer("review-events", ...)
    async for msg in consumer:
        await process_review_event(msg.value)
```

### 3. External API Clients
```python
# Each integration has a client class
class GoogleReviewsClient:
    async def list_locations(self, account_id): ...
    async def reply_to_review(self, review_id, text): ...
```

### 4. Encrypted Token Storage
```python
# Channel tokens encrypted at rest
access_token = Column(Text, nullable=False)  # Actually encrypted via property
```

## Authentication Flow

```
Login → JWT (15m) + Refresh Cookie (7d) + CSRF Cookie
         │
         ├─ Access Token → Authorization header
         ├─ Refresh Token → HttpOnly cookie (auto-sent)
         └─ CSRF Token → Readable cookie + X-CSRF-Token header
```

## Multi-Tenancy (Current State)

**Single-tenant per user.** No organizations/teams yet.
- All resources scoped to `user_id`
- Demo mode overrides for analytics display only

## Scaling Characteristics

| Component | Current | Bottleneck |
|-----------|---------|------------|
| API | Single replica (dev) | CPU on LLM calls |
| PostgreSQL | Single primary | Connections (pool: 10+10) |
| Redis | Single instance | Memory |
| Kafka | Single broker | Partition count |
| Workers | In-process (lifespan) | No horizontal scaling |

## Observability (Current)

| Signal | Implementation |
|--------|----------------|
| Logs | Structured JSON to stdout |
| Metrics | None (Prometheus client not added) |
| Traces | None (OpenTelemetry not added) |
| Health | `/health` endpoint only |
| Errors | Sentry (if DSN configured) |

## Deployment (Current)

- **Local**: Docker Compose (API, Postgres, Redis, Kafka, Zookeeper)
- **Production**: Not defined (no Kubernetes manifests, no Terraform)
- **CI/CD**: None configured

## Technical Debt / Known Gaps

1. **No metrics/tracing** - Cannot debug performance
2. **Workers in-process** - Cannot scale independently
3. **Single Kafka broker** - No HA
4. **No DB read replicas** - All queries on primary
5. **No CDN for assets** - Direct serving
6. **No API versioning strategy** - v1 only
7. **No integration tests** - Only unit tests
8. **No load testing** - Unknown capacity