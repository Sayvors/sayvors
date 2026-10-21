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
| POST | `/google/verify` | Verify Google sign-in credential |
| POST | `/verify-email` | Verify email with token |
| POST | `/facebook/verify` | Verify Facebook sign-in credential |
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
| GET | `/groups` | List location groups |
| POST | `/groups` | Create a location group |
| PATCH | `/groups/{group_id}` | Update a location group |
| DELETE | `/groups/{group_id}` | Delete a location group |
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
| POST | `/sync-metrics` | Refresh per-post Google metrics |
| POST | `/ai-draft` | Draft post text and metadata with the tenant's enabled AI model |

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
| GET | `/messaging/overview` | Messaging volume and response-health overview |
| GET | `/timeseries` | Daily time series data |
| GET | `/issues` | List location issues |
| POST | `/issues/refresh` | Refresh detected location issues |
| PATCH | `/issues/{issue_id}` | Update a location issue |
| GET | `/reviews/insights` | Enriched review list |
| POST | `/reviews/insights/{insight_id}/skip` | Skip a review insight |
| POST | `/reviews/insights/{insight_id}/dismiss-edit` | Dismiss an edited insight |
| POST | `/reviews/insights/{insight_id}/meaning` | Save or update the meaning of an insight |
| POST | `/reviews/insights/{insight_id}/flag-abuse` | Flag an insight as abusive |
| POST | `/reviews/insights/{insight_id}/abuse-verdict` | Record an abuse verdict |
| POST | `/reviews/insights/{insight_id}/abuse-reported` | Record that abuse was reported |
| POST | `/reviews/insights/{insight_id}/clear-abuse` | Clear an abuse flag |
| GET | `/review-intelligence` | Get stored AI analysis |
| POST | `/review-intelligence/analyze` | Run AI analysis |
| GET | `/topics` | Topic analysis |
| GET | `/problems` | Problem detection |
| GET | `/products` | Product/service intelligence |
| GET | `/visibility` | Google visibility metrics |
| GET | `/acquisition` | Customer acquisition |
| GET | `/opportunities` | Growth opportunities |
| GET | `/growth/keywords` | Growth keyword analysis |
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
| POST | `/google/connect-ticket` | Create a short-lived ticket for Google channel connection |
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
| POST | `/{channel_id}/reviews/verify-posted` | Verify externally posted review replies |
| POST | `/{channel_id}/reviews/{reply_id}/retry` | Retry a failed review reply |
| POST | `/{channel_id}/test-review` | Run the review-reply test pipeline |
| POST | `/publish` | Publish one post to many destinations |
| GET | `/publish` | List publish jobs (filter by status/platform) |
| GET | `/publish/status` | Batch poll publish job status |
| GET | `/publish/{job_id}` | Poll single publish job |
| POST | `/publish/{job_id}/delete` | Delete published post from platforms |
| POST | `/publish/{job_id}/cancel` | Cancel queued/scheduled job |
| POST | `/publish/delete` | Delete many published posts (body: `job_ids`, optional `platforms`) |

`GET /publish` and `POST /publish/delete` return the same job shape:
`job_id`, `status`, `platform`, `method`, `external_asset_id`, `caption`,
`media_url`, `scheduled_at`, `result`, `last_error`, `batch_id`. The posts
feed renders a card per job from those fields and removes a post by ticking
it and calling `/publish/delete` — a job that has not gone out yet is
cancelled instead of deleted, and one that already went out is deleted from
the platform it was published to (best effort per platform).

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
| GET | `/usage/summary` | Read the current user's LLM usage summary |

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
| PATCH | `/` | Update profile fields |
| PATCH | `/preferences` | Update theme and language preferences |
| PUT | `/response-style` | Set WhatsApp response style |
| PUT | `/voice-replies` | Configure voice-reply tier |
| PUT | `/typing-indicator` | Enable or disable outbound typing indicators |
| GET | `/usage` | Read account usage |
| GET | `/feedback` | List the current user's feedback |
| POST | `/feedback` | Submit feedback |
| GET | `/business` | Read the generated business profile |
| PUT | `/business` | Update the business profile |
| POST | `/business/regenerate` | Regenerate the profile from databank content |

---

## Localith (`/api/v1/integrations/localith`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/config` | Check whether the server has a Localith API key configured |
| GET | `/listings` | List listings available from Localith |
| POST | `/test` | Test access to a listing |
| POST | `/sync` | Sync one listing or all connected listings |
| GET | `/connections` | List all connected listings |
| GET | `/connection` | Get connection status |
| GET | `/profile` | Read a connected listing's synced profile and metrics |
| GET | `/profiles/aggregate` | Read aggregate totals across connected listings |
| PUT | `/connection` | Connect a Localith listing |
| PUT | `/connection/api-key` | Save a tenant-specific Localith API key |
| DELETE | `/connection/api-key` | Remove the tenant-specific API key |
| PATCH | `/listing` | Update a connected listing |
| DELETE | `/connection` | Disconnect a Localith listing |

---

## Text to Speech (`/api/v1/tts`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/voices` | List available voices (optional `language` filter) |
| POST | `/convert` | Create a text-to-speech job |
| GET | `/jobs` | List the current user's TTS jobs |
| GET | `/jobs/{job_id}` | Read a TTS job |

## Speech to Text (`/api/v1/stt`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/transcribe` | Create a speech-to-text job |
| GET | `/jobs` | List the current user's transcription jobs |
| GET | `/jobs/{job_id}` | Read a transcription job |

---

## RAG (`/api/v1/rag`)

See the [RAG / Databanks guide](rag.md) for the ingestion and query workflows.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/databanks` | Create a databank |
| GET | `/databanks` | List databanks |
| GET | `/databanks/{databank_id}` | Read a databank |
| DELETE | `/databanks/{databank_id}` | Delete a databank |
| POST | `/databanks/{databank_id}/documents` | Upload a document |
| GET | `/databanks/{databank_id}/documents` | List documents |
| DELETE | `/databanks/{databank_id}/documents/{doc_id}` | Delete a document |
| GET | `/databanks/{databank_id}/documents/{doc_id}/preview` | Preview parsed document content |
| POST | `/databanks/{databank_id}/scrape` | Queue a website scrape |
| POST | `/databanks/{databank_id}/process` | Process pending documents |
| POST | `/databanks/{databank_id}/documents/{doc_id}/process` | Process one document |
| GET | `/jobs` | List the current user's ingestion jobs |
| POST | `/databanks/{databank_id}/search` | Search indexed document chunks |
| POST | `/databanks/{databank_id}/sources/test` | Test a live database connection without saving |
| POST | `/databanks/{databank_id}/sources` | Save a tested live database source |
| GET | `/databanks/{databank_id}/sources` | List live database sources |
| DELETE | `/databanks/{databank_id}/sources/{source_id}` | Delete a database source |
| GET | `/databanks/{databank_id}/sources/{source_id}/schema` | List source tables |
| GET | `/databanks/{databank_id}/sources/{source_id}/tables/{table}` | Preview rows from a table |
| POST | `/databanks/{databank_id}/sources/{source_id}/query` | Run a read-only SQL query |
| POST | `/databanks/{databank_id}/sources/{source_id}/ingest` | Ingest query results into the databank |
| POST | `/databanks/{databank_id}/reindex` | Queue re-embedding of the databank |
| POST | `/databanks/{databank_id}/retry` | Retry pending, processing, or failed documents |
| POST | `/databanks/{databank_id}/ask` | Ask an agentic question over databank tools |

---

## Email (`/api/v1/email`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/otp/request` | Request an OTP email |
| POST | `/otp/verify` | Verify OTP |
| POST | `/send` | Send an email using the configured sender |

---

## Assistant (`/api/v1/assistant`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/chat` | Send a chat request and receive a complete response |
| POST | `/chat/stream` | Stream a chat response |

---

## Billing (`/api/v1/billing`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/budget` | Read plan and remaining AI credit balance |
| GET | `/profile` | Read billing profile |
| PUT | `/profile` | Create or update billing profile |
| GET | `/methods` | List saved payment methods |
| POST | `/gateway/tokenize` | Tokenize card metadata using the current stub gateway |
| POST | `/gateway/charge` | Exercise the stub charge flow; does not move money |
| POST | `/methods` | Add a saved payment method |
| POST | `/methods/{method_id}/default` | Set the default payment method |
| DELETE | `/methods/{method_id}` | Remove a payment method |

The gateway endpoints currently use a stub provider; they do not process real
payments or grant credits.

---

## Team (`/api/v1/team`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/permissions` | Read permission catalog and role templates |
| GET | `/context` | Read the current member's tenant, role, and permissions |
| GET | `/roles` | List tenant roles |
| POST | `/roles` | Create a role |
| PATCH | `/roles/{role_id}` | Update a role |
| DELETE | `/roles/{role_id}` | Delete a role |
| GET | `/members` | List tenant members |
| GET | `/channels` | List channels visible to the member |
| PATCH | `/members/{member_id}` | Update a member's role, status, or channel access |
| DELETE | `/members/{member_id}` | Remove a member |
| POST | `/invites` | Invite a member |
| GET | `/invites/preview` | Preview an invite using its token |
| POST | `/invites/accept` | Accept an invite (token-authenticated; may be pre-login) |
| POST | `/invites/{member_id}/resend` | Resend a member invite |
| DELETE | `/invites/{member_id}` | Revoke an invite |

Except for invite preview and acceptance, requests require authentication
and are checked against tenant permissions.

---

## Notifications (`/api/v1/notifications`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/categories` | List notification categories |
| GET | `/` | List notifications |
| GET | `/unread-count` | Read unread count |
| GET | `/settings` | Read notification preferences |
| PATCH | `/settings` | Update notification preferences |
| POST | `/{notification_id}/read` | Mark one notification as read |
| POST | `/read-all` | Mark all notifications as read |

---

## Feedback

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/feedback/status` | Read feedback submission availability |
| POST | `/api/v1/feedback` | Submit feedback |
| GET | `/api/v1/admin/feedback` | List submitted feedback |

---

## Review Engine (`/api/v1/review-engine`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/generate` | Generate a review reply |
| POST | `/generate-stream` | Stream review-reply generation |
| GET | `/dialects` | List available dialects |
| GET | `/tones` | List available tones |
| GET | `/strategies` | List review-reply strategies |
| GET | `/strategies/{strategy_id}` | Read a strategy |
| PUT | `/strategies/{strategy_id}` | Update a strategy |
| GET | `/logs` | Read review-engine logs |

Admin and tenant permissions may restrict access to strategy and log operations.

## CSV Review Data (`/api/v1/csv`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/upload` | Upload a review CSV |
| GET | `/uploads` | List CSV uploads |
| DELETE | `/uploads/{upload_id}` | Delete an upload |
| POST | `/search` | Search uploaded review data |
| GET | `/uploads/{upload_id}/rows` | Read rows from an upload |

---

## Media (`/api/v1/media`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/upload` | Upload media |
| GET | `/` | List media |
| POST | `/` | Create a media publishing record |
| GET | `/{media_id}` | Read a media item |
| PUT | `/{media_id}` | Update a media item |
| DELETE | `/{media_id}` | Delete a media item |
| POST | `/{media_id}/publish` | Publish media |
| POST | `/sync` | Sync media publishing status |

---

## Inbox (`/api/v1/inbox`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| WebSocket | `/ws` | Stream authenticated inbox events for the current tenant |
| GET | `/threads` | List message threads |
| GET | `/threads/{channel_id}/{contact_phone}` | Read a thread's messages |
| POST | `/send` | Send a message in a thread |

Browsers authenticate the WebSocket with the access-token cookie. Non-browser
clients may use the `token` query parameter; avoid query-string tokens where
URLs may be logged or retained.

---

## Leads (`/api/v1/leads`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | List leads |
| GET | `/settings` | Read lead escalation settings |
| PATCH | `/settings` | Update lead escalation settings |
| PATCH | `/{lead_id}` | Update a lead |

---

## Review Issues (`/api/v1/reviews/issues`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | List review issues |
| GET | `/by-ticket/{ticket_number}` | Look up an issue by ticket number |
| POST | `/{issue_id}/handoff-code` | Create or refresh a handoff code |
| PATCH | `/{issue_id}` | Update an issue |

---

## Meta Integrations

Meta connection, publishing, messaging, and webhook routes are implemented
under `/api/v1/meta` and `/api/v1/meta/webhooks`. The provider-specific
onboarding and webhook setup are documented in the
[Meta integration guides](../integrations/meta/architecture.md),
[OAuth guide](../integrations/meta/oauth.md), and
[webhook guide](../integrations/meta/webhooks.md).

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/meta/connections` | List connected Meta providers |
| POST | `/api/v1/meta/{provider}/connect` | Start a provider connection |
| GET | `/api/v1/meta/{provider}/callback` | Complete the provider OAuth callback |
| GET | `/api/v1/meta/{provider}/assets` | List provider assets |
| POST | `/api/v1/meta/{provider}/assets/select` | Select assets for a connection |
| POST | `/api/v1/meta/{provider}/validate` | Validate a provider connection |
| DELETE | `/api/v1/meta/{provider}/disconnect` | Disconnect a provider; `revoke` and `delete_data` are optional query parameters |
| POST | `/api/v1/meta/instagram/discover` | Discover Instagram accounts linked to connected Pages |
| GET | `/api/v1/meta/connect-sdk` | Serve the same-origin Meta JavaScript SDK proxy |
| GET | `/api/v1/meta/connect-sdk-bundle` | Serve the same-origin Meta SDK bundle proxy |
| GET | `/api/v1/meta/webhooks` | Verify Meta webhook callback configuration |
| POST | `/api/v1/meta/webhooks` | Receive Meta webhook events |
| GET | `/api/v1/meta/whatsapp/smb-sync-status` | Read WhatsApp Coexistence sync status |
| GET | `/api/v1/meta/whatsapp/usage` | Read the tenant's monthly Sayvors WhatsApp quota usage |
| POST | `/api/v1/meta/whatsapp/session` | Complete WhatsApp Embedded Signup |
| POST | `/api/v1/meta/whatsapp/{phone_number_id}/register` | Register a WhatsApp phone number |
| GET | `/api/v1/meta/whatsapp/{phone_number_id}/profile` | Read the WhatsApp business profile |
| PATCH | `/api/v1/meta/whatsapp/{phone_number_id}/profile` | Update the WhatsApp business profile |
| POST | `/api/v1/meta/whatsapp/{phone_number_id}/profile-photo` | Upload a WhatsApp profile photo |
| GET | `/api/v1/meta/instagram/{ig_id}/profile` | Read an Instagram business profile |
| GET | `/api/v1/meta/instagram/{ig_id}/audience` | Read engaged contacts and available audience demographics |
| GET | `/api/v1/meta/instagram/{ig_id}/posts` | List Instagram posts |
| GET | `/api/v1/meta/instagram/{ig_id}/stories` | List Instagram stories |
| GET | `/api/v1/meta/instagram/{ig_id}/comments` | List comments for Instagram media |
| POST | `/api/v1/meta/instagram/{ig_id}/comments/{comment_id}/replies` | Reply to an Instagram comment |
| POST | `/api/v1/meta/instagram/{ig_id}/comments/{comment_id}/hide` | Hide or unhide an Instagram comment |
| DELETE | `/api/v1/meta/instagram/{ig_id}/comments/{comment_id}` | Delete an Instagram comment |
| POST | `/api/v1/meta/instagram/{ig_id}/posts/publish` | Publish Instagram feed media and optional stories |
| GET | `/api/v1/meta/instagram/{ig_id}/publishing-limit` | Read the Instagram publishing limit |
| GET | `/api/v1/meta/instagram/{ig_id}/locations` | Search locations for an Instagram post |
| POST | `/api/v1/meta/instagram/{ig_id}/caption/suggest` | Generate an Instagram caption suggestion |
| GET | `/api/v1/meta/instagram/{ig_id}/media/{media_id}/insights` | Read available Instagram media insights |
| GET | `/api/v1/meta/facebook/{page_id}/profile` | Read Facebook Page profile |
| GET | `/api/v1/meta/facebook/{page_id}/posts` | List Facebook Page posts |
| GET | `/api/v1/meta/facebook/{page_id}/scheduled` | List scheduled Facebook Page posts |
| POST | `/api/v1/meta/facebook/{page_id}/posts/publish` | Publish or schedule a Facebook Page post |
| GET | `/api/v1/meta/facebook/{page_id}/comments` | List Facebook Page post comments |
| POST | `/api/v1/meta/facebook/{page_id}/comments/{comment_id}/replies` | Reply to a Facebook comment |
| POST | `/api/v1/meta/facebook/{page_id}/comments/{comment_id}/hide` | Hide or unhide a Facebook comment |
| DELETE | `/api/v1/meta/facebook/{page_id}/comments/{comment_id}` | Delete a Facebook comment |

Most connection and asset operations require an authenticated tenant and a
matching team permission. `refresh` query parameters on cached profile/list
routes bypass the short-lived cache. Media published through Meta must be
fetchable by Meta's servers at a public URL. See the linked integration guides
and the running OpenAPI schema for request and response models.

---

## Service Diagnostics

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/metrics` | In-process Prometheus-format HTTP request metrics |
| GET | `/api/v1/redis/health` | Redis availability check |
| GET | `/api/v1/kafka/health` | Kafka availability check |

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

---

## Admin (`/api/v1/admin`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/login` | Admin login (httpOnly cookie) |
| POST | `/logout` | Admin logout |
| GET | `/me` | Session check |
| GET | `/overview` | Platform overview totals |
| GET | `/overview/stats` | Windowed stats (totals + delta + last 24h + platforms) |
| GET | `/overview/stats/live` | Live stats (last N minutes, polls every 15s) |
| GET | `/health` | Per-service health + recent failures |
| GET | `/tenants` | List tenants |
| GET | `/tenants/{user_id}` | Tenant detail |
| GET | `/tenants/{user_id}/usage` | Tenant LLM usage |
| POST | `/tenants/{user_id}/plan` | Grant plan + credits |
| GET | `/llm` | LLM provider status |
| PUT | `/llm/{provider}` | Update provider key/enabled |
| POST | `/llm/{provider}/test` | Test provider connection |
| PUT | `/llm/{provider}/models/{model_id}` | Enable/disable model |
| POST | `/llm/{provider}/models/{model_id}/test` | Test model |
| POST | `/llm/models` | Add a saved model |
| DELETE | `/llm/{provider}/models/{model_id}` | Delete a saved provider model |
| GET | `/llm/{provider}/remote-models` | List remote models |
| GET | `/usage/overview` | Global token metering |
| GET | `/usage/voice` | Voice TTS metering |
| GET | `/voice-engines` | List voice engines |
| POST | `/voice-engines` | Create voice engine |
| GET | `/voice-engines/fish-voices` | Browse Fish Audio catalog |
| POST | `/voice-engines/{engine_id}/test` | Test voice engine |
| PUT | `/voice-engines/{engine_id}` | Update voice engine |
| DELETE | `/voice-engines/{engine_id}` | Delete voice engine |
| GET | `/dialects` | List dialects |
| POST | `/dialects` | Create dialect |
| DELETE | `/dialects/{code}` | Delete dialect |
| GET | `/tones` | List tones |
| POST | `/tones` | Create tone |
| PUT | `/tones/{code}` | Update tone |
| DELETE | `/tones/{code}` | Delete tone |
| GET | `/models` | List saved models |

### Overview Stats
```http
GET /api/v1/admin/overview/stats?window=30d
Authorization: Bearer <admin_token>
X-CSRF-Token: ...
```

Query params: `window` = `24h` \| `7d` \| `30d` \| `90d` \| `1y` (default `30d`)

**Response (200):**
```json
{
  "window": "30d",
  "window_start": "2026-10-10T13:53:24+00:00",
  "generated_at": "2026-10-17T13:53:24+00:00",
  "totals": { "users": 18, "tenants": 16, "businesses": 3, "reviews": 17, "messages": 2, "posts": 1 },
  "window_delta": { "users": 11, "tenants": 11, "businesses": 0, "reviews": 0, "messages": 2, "messages_in": 1, "messages_out": 1, "ai_replies": 0, "posts": 0 },
  "last_24h": { "users": 0, "reviews": 0, "messages": 0, "messages_in": 0, "messages_out": 0, "ai_replies": 0 },
  "platforms": [
    { "platform": "whatsapp", "label": "WhatsApp", "connected": 4, "connected_total": 4, "messages": 2, "messages_in": 1, "messages_out": 1 },
    { "platform": "facebook", "label": "Facebook", "connected": 1, "connected_total": 2, "messages": 0, "messages_in": 0, "messages_out": 0 },
    { "platform": "instagram", "label": "Instagram", "connected": 1, "connected_total": 1, "messages": 0, "messages_in": 0, "messages_out": 0 },
    { "platform": "x", "label": "X", "connected": 0, "connected_total": 0, "messages": 0, "messages_in": 0, "messages_out": 0 },
    { "platform": "telegram", "label": "Telegram", "connected": 0, "connected_total": 0, "messages": 0, "messages_in": 0, "messages_out": 0 },
    { "platform": "linkedin", "label": "LinkedIn", "connected": 0, "connected_total": 0, "messages": 0, "messages_in": 0, "messages_out": 0 },
    { "platform": "google_reviews", "label": "Google Reviews", "connected": 4, "connected_total": 4, "messages": 0, "messages_in": 0, "messages_out": 0 }
  ]
}
```

### Live Stats
```http
GET /api/v1/admin/overview/stats/live?minutes=30
Authorization: Bearer <admin_token>
X-CSRF-Token: ...
```

Query params: `minutes` = `15`–`120` (default `30`)

**Response (200):**
```json
{
  "minutes": 30,
  "generated_at": "2026-10-17T13:53:24+00:00",
  "messages": 2,
  "messages_in": 1,
  "messages_out": 1,
  "ai_replies": 0,
  "new_users": 0,
  "new_reviews": 0,
  "businesses_connected": 3,
  "businesses_disconnected": 0,
  "active_platforms": 3,
  "top_platform": "whatsapp"
}
```

---

## Storage (`/api/v1/storage`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/upload` | Upload photo/video (returns public URL) |
| GET | `/objects` | List caller's uploaded media objects |
| GET | `/objects/{key}` | Fetch metadata for an owned object |
| PUT | `/objects/{key}` | Replace content at an owned key |
| DELETE | `/objects/{key}` | Delete an owned object |
| POST | `/presign` | Create temporary private download URL |

### Upload Object
```http
POST /api/v1/storage/upload
Authorization: Bearer <token>
X-CSRF-Token: ...
Content-Type: multipart/form-data

file: <binary>
```

**Response (200):**
```json
{
  "key": "u1/abc123.jpg",
  "url": "https://api.example.com/media-files/u1/abc123.jpg",
  "size": 1024,
  "content_type": "image/jpeg",
  "operation": "upload"
}
```

Storage backend is selected by env var: `S3_MEDIA_BUCKET`/`S3_DOCS_BUCKET` → S3, `GCS_PUBLIC_BUCKET`/`GCS_PRIVATE_BUCKET` → GCS, otherwise local disk. See `docs/database/README.md` for backend selection details.

---

## Publish (`/api/v1/channels/publish`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/publish` | Publish one post to many destinations (creates jobs) |
| GET | `/publish` | List publish jobs (filter by status/platform, paginated) |
| GET | `/publish/status?job_ids=...` | Batch poll publish job status |
| GET | `/publish/{job_id}` | Poll single publish job status |
| POST | `/publish/{job_id}/delete` | Delete a published post from selected platforms (or all) |
| POST | `/publish/{job_id}/cancel` | Cancel a queued/scheduled publish job |

### Publish Post
```http
POST /api/v1/channels/publish
Authorization: Bearer <token>
X-CSRF-Token: ...
Content-Type: application/json

{
  "media_url": "https://api.example.com/media-files/u1/abc123.jpg",
  "media_type": "image",
  "media_key": "u1/abc123.jpg",
  "caption": "Check out our new menu!",
  "description": "Full details here.",
  "scheduled_at": "2026-10-25T10:00:00Z",  // optional, ISO-8601, must be in the future
  "delete_at": "2026-11-01T10:00:00Z",    // optional, ISO-8601, must be in the future and after scheduled_at
  "idempotency_key": "publish-123",
  "destinations": [
    { "platform": "instagram", "external_asset_id": "17841400000000000", "methods": ["post", "story"] },
    { "platform": "facebook", "external_asset_id": "123456789", "methods": ["post"] },
    { "platform": "whatsapp", "external_asset_id": "+15551234567", "methods": ["status"] },
    { "platform": "google_reviews", "external_asset_id": "locations/123456", "methods": ["update", "event", "offer"] }
  ]
}
```

Supported platforms: `whatsapp`, `facebook`, `instagram`, `google_reviews`.
Supported methods: `post`, `story`, `reel`, `status` (Meta), `update`, `event`,
`offer` (Google Business Profile), `profile`, `banner` (account surfaces —
see [publish-formats.md](../integrations/publish-formats.md)).
`media_type`: `image` or `video`. `scheduled_at`: ISO-8601 datetime in the future, or null.
`delete_at`: ISO-8601 datetime in the future, or null. When set, the post is
taken back down from every destination on that date — a promotional post with
an end date. The removal is queued once the post is actually live, and it
calls the platform's real delete, so the post really comes down.

**Response (200):**
```json
[
  { "job_id": "uuid-1", "status": "queued", "lane": "publishing", "platform": "instagram", "method": "post", "created_at": "2026-10-17T13:53:24+00:00" },
  { "job_id": "uuid-2", "status": "queued", "lane": "publishing", "platform": "instagram", "method": "story", "created_at": "2026-10-17T13:53:24+00:00" },
  { "job_id": "uuid-3", "status": "queued", "lane": "publishing", "platform": "facebook", "method": "post", "created_at": "2026-10-17T13:53:24+00:00" }
]
```

Creates one Job per (destination, method) pair on the `publishing` lane. Jobs run asynchronously via the job runner; poll `/publish/{job_id}` or `/publish/status` for status.

### List Publish Jobs
```http
GET /api/v1/channels/publish?status=succeeded&platform=facebook&limit=50&offset=0
Authorization: Bearer <token>
```

**Response (200):** Array of `JobOut` (same shape as above, newest-first). Optional filters: `status`, `platform`. Paginated with `limit`/`offset`.

### Batch Publish Status
```http
GET /api/v1/channels/publish/status?job_ids=uuid-1,uuid-2,uuid-3
Authorization: Bearer <token>
```

**Response (200):** Array of `JobOut` for the requested ids (max 100). Unknown or cross-tenant ids are silently dropped.

### Publish Status (single)
```http
GET /api/v1/channels/publish/{job_id}
Authorization: Bearer <token>
```

**Response (200):**
```json
{ "job_id": "uuid-1", "status": "succeeded", "lane": "publishing", "platform": "instagram", "method": "post", "result": { "id": "..." }, "created_at": "2026-10-17T13:53:24+00:00" }
```

Status values: `accepted`, `queued`, `running`, `retrying`, `blocked`, `succeeded`, `failed`, `cancelled`, `dead`.

### Delete Published Post
```http
POST /api/v1/channels/publish/{job_id}/delete
Authorization: Bearer <token>
X-CSRF-Token: ...
Content-Type: application/json

{ "platforms": ["facebook", "instagram"] }   // or ["all"], or omit body for all
```

If the job is still queued/scheduled, it is cancelled (nothing to delete yet).
If the job has succeeded, calls the provider's delete API per selected platform.
Best-effort per platform: a failure on one does not roll back the others.

**Response (200):** `JobOut` with status `cancelled`.

Platform support:
- `facebook`: DELETE /{post_id}
- `instagram`: DELETE /{media_id}
- `google_reviews`: DELETE /v1/.../localPosts/{postId}
- `whatsapp`: 501 (statuses are ephemeral, auto-expire after 24h)

### Cancel Publish Job
```http
POST /api/v1/channels/publish/{job_id}/cancel
Authorization: Bearer <token>
X-CSRF-Token: ...
Content-Type: application/json

{ "reason": "changed my mind" }   // optional
```

Cancels a job in `accepted`, `queued`, `retrying`, or `blocked` state.
Already-published jobs must use the delete endpoint.

**Response (200):** `JobOut` with status `cancelled`.