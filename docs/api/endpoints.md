# API Endpoints Reference

## Authentication (`/api/v1/auth`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/signup` | Register new user |
| POST | `/login` | User login |
| POST | `/refresh` | Refresh access token |
| POST | `/logout` | Logout (single/all devices) |
| POST | `/csrf-token` | Get new CSRF token |
| POST | `/forgot-password` | Request password reset |
| POST | `/reset-password` | Reset password with token |
| POST | `/verify-email` | Verify email with token |
| POST | `/verify-otp` | Verify signup OTP |
| GET | `/me` | Get current user profile |
| PATCH | `/me` | Update current user profile |
| GET | `/sessions` | List user sessions |

### Signup
```http
POST /api/v1/auth/signup
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "securepassword123",
  "first_name": "John",
  "last_name": "Doe"
}
```

**Response (201):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "first_name": "John",
    "last_name": "Doe",
    "email_verified": false,
    "onboarded": false,
    "theme": "light",
    "language": "en",
    "created_at": "2024-01-15T10:30:00Z"
  }
}
```

### Login
```http
POST /api/v1/auth/login
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "securepassword123"
}
```

### Refresh Token
```http
POST /api/v1/auth/refresh
Cookie: refresh_token=...
```

### Logout
```http
POST /api/v1/auth/logout
Content-Type: application/json
X-CSRF-Token: ...

{
  "refresh_token": "...",
  "all_devices": false
}
```

---

## Locations (`/api/v1/locations`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | List user's locations |
| GET | `/{listing_id}` | Get location profile |
| PUT | `/{listing_id}` | Update location profile |

### List Locations
```http
GET /api/v1/locations/
Authorization: Bearer <token>
```

**Response (200):**
```json
[
  {
    "listing_id": "12345",
    "name": "My Business",
    "address": "123 Main St, City, State",
    "status": "active",
    "source": "localith"
  }
]
```

### Get Location Profile
```http
GET /api/v1/locations/{listing_id}
Authorization: Bearer <token>
```

**Response (200):**
```json
{
  "listing_id": "12345",
  "name": "My Business",
  "description": "Business description",
  "categories": ["restaurant", "cafe"],
  "address": "123 Main St",
  "phone": "+15551234567",
  "website": "https://example.com",
  "hours": {
    "monday": {"open": "09:00", "close": "17:00"},
    "tuesday": {"open": "09:00", "close": "17:00"}
  },
  "service_area": ["city", "suburb"],
  "attributes": {"wifi": true, "parking": true},
  "photos": ["url1", "url2"],
  "rating": 4.5,
  "review_count": 120,
  "source": "google"
}
```

### Update Location
```http
PUT /api/v1/locations/{listing_id}
Authorization: Bearer <token>
Content-Type: application/json
X-CSRF-Token: ...

{
  "description": "Updated description",
  "categories": ["restaurant", "cafe", "bakery"],
  "hours": {
    "monday": {"open": "08:00", "close": "18:00"}
  },
  "service_area": ["city", "suburb", "downtown"],
  "attributes": {"wifi": true, "parking": true, "outdoor_seating": true}
}
```

---

## Posts (`/api/v1/posts`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/` | Create post |
| GET | `/` | List posts |
| GET | `/{post_id}` | Get post |
| PUT | `/{post_id}` | Update post |
| DELETE | `/{post_id}` | Delete post |
| POST | `/{post_id}/publish` | Publish post now |
| POST | `/sync` | Sync due scheduled posts |

### Create Post
```http
POST /api/v1/posts/
Authorization: Bearer <token>
Content-Type: application/json
X-CSRF-Token: ...

{
  "listing_id": "12345",
  "content": "Check out our new menu!",
  "media_urls": ["https://example.com/photo.jpg"],
  "publish_at": "2024-01-20T10:00:00Z",  // optional, omit for immediate
  "status": "scheduled"  // or "published", "draft"
}
```

### List Posts
```http
GET /api/v1/posts/?listing_id=12345
Authorization: Bearer <token>
```

---

## Analytics (`/api/v1/analytics`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/overview` | KPI overview |
| GET | `/timeseries` | Daily time series data |
| GET | `/reviews/insights` | Enriched review list |
| GET | `/review-intelligence` | Get stored AI analysis |
| POST | `/review-intelligence/analyze` | Run AI analysis |
| GET | `/topics` | Topic analysis |
| GET | `/problems` | Problem detection |
| GET | `/products` | Product/service intelligence |
| GET | `/visibility` | Google visibility metrics |
| GET | `/acquisition` | Customer acquisition |
| GET | `/opportunities` | Growth opportunities |
| GET | `/benchmark/comparison` | Benchmark vs peers |
| GET | `/executive-summary` | AI business briefing |

### Overview
```http
GET /api/v1/analytics/overview?channel_id=abc&days=30
Authorization: Bearer <token>
```

**Response (200):**
```json
{
  "period": { "start": "2024-01-01", "end": "2024-01-30" },
  "ratings": { "average": 4.3, "count": 150, "distribution": { "5": 60, "4": 50, "3": 25, "2": 10, "1": 5 } },
  "sentiment": { "positive": 65, "neutral": 25, "negative": 10 },
  "response": { "rate": 78, "avg_time_hours": 4.2 },
  "scores": { "reputation": 82, "engagement": 75, "visibility": 68 },
  "google_performance": { "impressions": 12500, "website_clicks": 890, "call_clicks": 340, "direction_requests": 210 }
}
```

### Timeseries
```http
GET /api/v1/analytics/timeseries?channel_id=abc&days=30
Authorization: Bearer <token>
```

### Review Insights
```http
GET /api/v1/analytics/reviews/insights?channel_id=abc&sentiment=negative&limit=50&offset=0
Authorization: Bearer <token>
```

---

## Channels (`/api/v1/channels`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/` | Connect channel |
| GET | `/` | List channels |
| GET | `/{channel_id}` | Get channel |
| DELETE | `/{channel_id}` | Disconnect channel |
| GET | `/{channel_id}/verification` | Get verification status |
| POST | `/{channel_id}/verification` | Request verification |
| GET | `/{channel_id}/services` | List business services |
| POST | `/{channel_id}/services` | Create service |
| PUT | `/{channel_id}/services/{service_id}` | Update service |
| DELETE | `/{channel_id}/services/{service_id}` | Delete service |
| POST | `/{channel_id}/messages` | Send message |
| GET | `/{channel_id}/messages` | List messages |
| POST | `/webhook/{platform}` | Receive webhook |
| GET | `/google/connect` | Start Google OAuth |
| GET | `/google/callback` | Google OAuth callback |
| GET | `/{channel_id}/autoreply` | Get auto-reply config |
| PUT | `/{channel_id}/autoreply` | Update auto-reply config |
| GET | `/{channel_id}/reviews` | List review replies |
| POST | `/{channel_id}/reviews/{reply_id}/approve` | Approve reply |
| POST | `/{channel_id}/reviews/generate` | Generate AI reply |
| PUT | `/{channel_id}/reviews/{reply_id}` | Edit pending reply |
| POST | `/{channel_id}/reviews/{reply_id}/regenerate` | Regenerate reply |
| DELETE | `/{channel_id}/reviews/{reply_id}` | Reject reply |

### Connect Channel
```http
POST /api/v1/channels/
Authorization: Bearer <token>
Content-Type: application/json
X-CSRF-Token: ...

{
  "platform": "google_reviews",
  "platform_user_id": "12345",
  "display_name": "My Business",
  "access_token": "...",
  "refresh_token": "..."
}
```

### Webhook (Platform → API)
```http
POST /api/v1/channels/webhook/google_reviews
X-Hub-Signature-256: sha256=...
Content-Type: application/json

{ "review": { ... } }
```

---

## LLM (`/api/v1/llm`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/models` | List available models |
| POST | `/conversations` | Create conversation |
| GET | `/conversations` | List conversations |
| GET | `/conversations/{conv_id}` | Get conversation |
| POST | `/conversations/{conv_id}/messages` | Send message |
| GET | `/conversations/{conv_id}/messages` | List messages |
| POST | `/chat` | One-shot chat |
| POST | `/chat/stream` | Streaming chat (SSE) |

### List Models
```http
GET /api/v1/llm/models
Authorization: Bearer <token>
```

### Chat (Non-streaming)
```http
POST /api/v1/llm/chat
Authorization: Bearer <token>
Content-Type: application/json

{
  "model": "groq/llama-3.1-70b-versatile",
  "messages": [
    { "role": "user", "content": "Hello!" }
  ],
  "conversation_id": "optional-uuid",
  "system_prompt": "You are a helpful assistant."
}
```

### Chat (Streaming)
```http
POST /api/v1/llm/chat/stream
Authorization: Bearer <token>
Content-Type: application/json

{
  "model": "groq/llama-3.1-70b-versatile",
  "messages": [
    { "role": "user", "content": "Tell me a story" }
  ]
}
```

**Response:** Server-Sent Events (text/event-stream)
```
data: {"type": "content", "content": "Once"}
data: {"type": "content", "content": " upon"}
data: {"type": "content", "content": " a time..."}
data: [DONE]
```

---

## Profile (`/api/v1/profile`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Get profile |
| PUT | `/` | Update profile |
| GET | `/databanks` | List databanks |
| POST | `/databanks` | Create databank |
| GET | `/databanks/{id}` | Get databank |
| DELETE | `/databanks/{id}` | Delete databank |
| POST | `/databanks/{id}/crawl` | Crawl URL |
| POST | `/databanks/{id}/upload` | Upload file |

---

## Localith (`/api/v1/localith`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/connection` | Get connection status |
| POST | `/connect` | Connect EmbedSocial |
| DELETE | `/disconnect` | Disconnect |
| POST | `/sync` | Manual sync |
| GET | `/listings` | List locations |

---

## TTS/STT (`/api/v1/tts`, `/api/v1/stt`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/tts/synthesize` | Text to speech |
| POST | `/stt/transcribe` | Speech to text |

---

## RAG (`/api/v1/rag`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/query` | Query knowledge base |
| POST | `/databanks` | Create databank |
| GET | `/databanks` | List databanks |

---

## Email (`/api/v1/email`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/otp/send` | Send OTP email |
| POST | `/otp/verify` | Verify OTP |

---

## Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |

```http
GET /health
```

**Response (200):**
```json
{ "status": "ok" }
```