# SDK & Code Examples

## JavaScript/TypeScript Client

### Installation

```bash
npm install @sayvors/api-client
# or
yarn add @sayvors/api-client
```

### Basic Usage

```typescript
import { SayvorsClient } from '@sayvors/api-client';

const client = new SayvorsClient({
  baseUrl: 'http://localhost:8000', // or production URL
  // Tokens managed automatically via cookies
});

// Authentication
await client.auth.login('user@example.com', 'password123');
const user = await client.auth.getMe();

// Locations
const locations = await client.locations.list();
const location = await client.locations.get('listing-id');
await client.locations.update('listing-id', {
  description: 'Updated description',
  hours: { monday: { open: '09:00', close: '17:00' } }
});

// Posts
const post = await client.posts.create({
  listing_id: 'listing-id',
  content: 'Hello world!',
  media_urls: ['https://example.com/image.jpg'],
  publish_at: new Date('2024-01-20T10:00:00Z')
});

const posts = await client.posts.list({ listing_id: 'listing-id' });
await client.posts.publish(post.id);

// Analytics
const overview = await client.analytics.overview({ days: 30 });
const timeseries = await client.analytics.timeseries({ days: 30 });
const insights = await client.analytics.reviewInsights({ 
  sentiment: 'negative', 
  limit: 20 
});

// Channels
const channels = await client.channels.list();
await client.channels.connect({
  platform: 'google_reviews',
  display_name: 'My Business'
});

// LLM
const models = await client.llm.listModels();
const response = await client.llm.chat({
  model: 'groq/llama-3.1-70b-versatile',
  messages: [{ role: 'user', content: 'Hello!' }]
});

// Streaming
for await (const chunk of client.llm.streamChat({
  model: 'groq/llama-3.1-70b-versatile',
  messages: [{ role: 'user', content: 'Tell a story' }]
})) {
  process.stdout.write(chunk.content);
}
```

### React Hooks

```tsx
import { useAuth, useLocations, usePosts, useAnalytics } from '@sayvors/api-client/react';

function Dashboard() {
  const { user, login, logout } = useAuth();
  const { locations, loading: locLoading } = useLocations();
  const { posts, createPost } = usePosts();
  const { overview, timeseries } = useAnalytics({ days: 30 });

  if (!user) {
    return <LoginForm onLogin={login} />;
  }

  return (
    <div>
      <header>Welcome, {user.first_name}</header>
      <LocationsList locations={locations} loading={locLoading} />
      <PostsList posts={posts} onCreate={createPost} />
      <AnalyticsCharts overview={overview} timeseries={timeseries} />
    </div>
  );
}
```

## Python Client

### Installation

```bash
pip install sayvors-api-client
```

### Usage

```python
from sayvors import SayvorsClient

client = SayvorsClient(base_url="http://localhost:8000")

# Auth
await client.auth.login("user@example.com", "password123")
user = await client.auth.get_me()

# Locations
locations = await client.locations.list()
location = await client.locations.get("listing-id")
await client.locations.update("listing-id", description="New description")

# Posts
post = await client.posts.create(
    listing_id="listing-id",
    content="Hello from Python!",
    publish_at="2024-01-20T10:00:00Z"
)
posts = await client.posts.list(listing_id="listing-id")
await client.posts.publish(post.id)

# Analytics
overview = await client.analytics.overview(days=30)
timeseries = await client.analytics.timeseries(days=30)
insights = await client.analytics.review_insights(sentiment="negative", limit=20)

# LLM
models = await client.llm.list_models()
response = await client.llm.chat(
    model="groq/llama-3.1-70b-versatile",
    messages=[{"role": "user", "content": "Hello!"}]
)

# Streaming
async for chunk in client.llm.stream_chat(
    model="groq/llama-3.1-70b-versatile",
    messages=[{"role": "user", "content": "Tell a story"}]
):
    print(chunk.content, end="", flush=True)
```

## cURL Examples

### Authentication

```bash
# Login
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "password123"}' \
  -c cookies.txt

# Get profile (uses cookies)
curl -X GET http://localhost:8000/api/v1/auth/me \
  -b cookies.txt

# Refresh token
curl -X POST http://localhost:8000/api/v1/auth/refresh \
  -b cookies.txt

# Logout
curl -X POST http://localhost:8000/api/v1/auth/logout \
  -H "X-CSRF-Token: $(grep csrf_token cookies.txt | cut -f7)" \
  -b cookies.txt
```

### Locations

```bash
# List locations
curl -X GET http://localhost:8000/api/v1/locations/ \
  -H "Authorization: Bearer ACCESS_TOKEN"

# Get location
curl -X GET http://localhost:8000/api/v1/locations/LISTING_ID \
  -H "Authorization: Bearer ACCESS_TOKEN"

# Update location
curl -X PUT http://localhost:8000/api/v1/locations/LISTING_ID \
  -H "Authorization: Bearer ACCESS_TOKEN" \
  -H "X-CSRF-Token: CSRF_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"description": "Updated", "categories": ["restaurant"]}'
```

### Posts

```bash
# Create post
curl -X POST http://localhost:8000/api/v1/posts/ \
  -H "Authorization: Bearer ACCESS_TOKEN" \
  -H "X-CSRF-Token: CSRF_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"listing_id": "LISTING_ID", "content": "New post!", "status": "published"}'

# List posts
curl -X GET "http://localhost:8000/api/v1/posts/?listing_id=LISTING_ID" \
  -H "Authorization: Bearer ACCESS_TOKEN"

# Publish scheduled post
curl -X POST http://localhost:8000/api/v1/posts/POST_ID/publish \
  -H "Authorization: Bearer ACCESS_TOKEN" \
  -H "X-CSRF-Token: CSRF_TOKEN"
```

### Analytics

```bash
# Overview
curl -X GET "http://localhost:8000/api/v1/analytics/overview?days=30" \
  -H "Authorization: Bearer ACCESS_TOKEN"

# Timeseries
curl -X GET "http://localhost:8000/api/v1/analytics/timeseries?days=30" \
  -H "Authorization: Bearer ACCESS_TOKEN"

# Review insights
curl -X GET "http://localhost:8000/api/v1/analytics/reviews/insights?sentiment=negative&limit=20" \
  -H "Authorization: Bearer ACCESS_TOKEN"

# AI Analysis
curl -X POST http://localhost:8000/api/v1/analytics/review-intelligence/analyze \
  -H "Authorization: Bearer ACCESS_TOKEN" \
  -H "X-CSRF-Token: CSRF_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"channel_id": "CHANNEL_ID", "days": 90}'
```

### Channels

```bash
# Connect Google Reviews (starts OAuth)
curl -X GET "http://localhost:8000/api/v1/channels/google/connect?token=ACCESS_TOKEN"

# List channels
curl -X GET http://localhost:8000/api/v1/channels/ \
  -H "Authorization: Bearer ACCESS_TOKEN"

# Get auto-reply config
curl -X GET http://localhost:8000/api/v1/channels/CHANNEL_ID/autoreply \
  -H "Authorization: Bearer ACCESS_TOKEN"

# Update auto-reply
curl -X PUT http://localhost:8000/api/v1/channels/CHANNEL_ID/autoreply \
  -H "Authorization: Bearer ACCESS_TOKEN" \
  -H "X-CSRF-Token: CSRF_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"enabled": true, "tone": "friendly", "model": "groq/llama-3.1-70b-versatile"}'

# Generate AI reply
curl -X POST http://localhost:8000/api/v1/channels/CHANNEL_ID/reviews/generate \
  -H "Authorization: Bearer ACCESS_TOKEN" \
  -H "X-CSRF-Token: CSRF_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"review_id": "REVIEW_ID", "rating": 3, "review_text": "OK service", "reviewer_name": "John"}'
```

### LLM

```bash
# List models
curl -X GET http://localhost:8000/api/v1/llm/models \
  -H "Authorization: Bearer ACCESS_TOKEN"

# Chat
curl -X POST http://localhost:8000/api/v1/llm/chat \
  -H "Authorization: Bearer ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model": "groq/llama-3.1-70b-versatile", "messages": [{"role": "user", "content": "Hello!"}]}'

# Stream chat
curl -X POST http://localhost:8000/api/v1/llm/chat/stream \
  -H "Authorization: Bearer ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model": "groq/llama-3.1-70b-versatile", "messages": [{"role": "user", "content": "Tell a story"}]}' \
  --no-buffer
```

## Webhook Handling (Node.js/Express)

```javascript
const express = require('express');
const crypto = require('crypto');
const app = express();

app.use(express.json({ limit: '1mb', verify: (req, res, buf) => {
  req.rawBody = buf;
}}));

// Facebook/Instagram/WhatsApp
app.post('/webhook/facebook', (req, res) => {
  const signature = req.headers['x-hub-signature-256'];
  const secret = process.env.FACEBOOK_WEBHOOK_SECRET;
  
  const expected = 'sha256=' + crypto
    .createHmac('sha256', secret)
    .update(req.rawBody)
    .digest('hex');
  
  if (!crypto.timingSafeEqual(Buffer.from(signature), Buffer.from(expected))) {
    return res.status(403).send('Invalid signature');
  }
  
  // Process webhook
  handleFacebookWebhook(req.body);
  res.json({ status: 'ok' });
});

// Google Reviews
app.post('/webhook/google_reviews', async (req, res) => {
  // Google sends OAuth notifications
  await handleGoogleReviewNotification(req.body);
  res.json({ status: 'ok' });
});

async function handleFacebookWebhook(payload) {
  for (const entry of payload.entry) {
    for (const change of entry.changes) {
      if (change.field === 'reviews') {
        const review = change.value;
        // Forward to Sayvors API
        await fetch('https://api.sayvors.com/api/v1/channels/webhook/facebook', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'x-hub-signature-256': req.headers['x-hub-signature-256']
          },
          body: JSON.stringify(payload)
        });
      }
    }
  }
}

app.listen(3000, () => console.log('Webhook server running on port 3000'));
```

## Common Patterns

### Pagination Helper

```typescript
async function* fetchAllPages<T>(
  fetchPage: (offset: number, limit: number) => Promise<{ items: T[]; total: number }>,
  limit = 50
): AsyncGenerator<T> {
  let offset = 0;
  let hasMore = true;
  
  while (hasMore) {
    const { items, total } = await fetchPage(offset, limit);
    for (const item of items) yield item;
    offset += items.length;
    hasMore = offset < total;
  }
}

// Usage
for await (const post of fetchAllPages((offset, limit) => 
  client.posts.list({ listing_id: 'id', offset, limit })
)) {
  console.log(post);
}
```

### Retry Wrapper

```typescript
async function withRetry<T>(
  fn: () => Promise<T>,
  options: { maxRetries?: number; retryableCodes?: string[] } = {}
): Promise<T> {
  const { maxRetries = 3, retryableCodes = ['TOO_MANY_REQUESTS', 'BAD_GATEWAY', 'SERVICE_UNAVAILABLE'] } = options;
  
  for (let attempt = 0; ; attempt++) {
    try {
      return await fn();
    } catch (error) {
      if (error instanceof ApiError && 
          retryableCodes.includes(error.code) && 
          attempt < maxRetries) {
        const delay = Math.min(1000 * 2 ** attempt, 30000);
        await new Promise(r => setTimeout(r, delay + Math.random() * 1000));
        continue;
      }
      throw error;
    }
  }
}
```

### File Upload

```bash
# Upload media for post
curl -X POST http://localhost:8000/api/v1/posts/ \
  -H "Authorization: Bearer ACCESS_TOKEN" \
  -H "X-CSRF-Token: CSRF_TOKEN" \
  -F 'data={"listing_id": "LISTING_ID", "content": "Photo post"}' \
  -F 'media=@/path/to/image.jpg'
```

```typescript
// TypeScript file upload
const formData = new FormData();
formData.append('data', JSON.stringify({ listing_id: 'id', content: 'Photo' }));
formData.append('media', fileInput.files[0]);

await fetch('/api/v1/posts/', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${accessToken}`,
    'X-CSRF-Token': csrfToken
  },
  body: formData,
  credentials: 'include'
});
```