# Webhooks

## Overview

Webhooks allow external platforms (Google, Facebook, Instagram, etc.) to send real-time events to the Sayvors API.

## Webhook Endpoint

```
POST /api/v1/channels/webhook/{platform}
```

### Supported Platforms

| Platform | Header | Signature Algorithm |
|----------|--------|---------------------|
| Facebook | `x-hub-signature-256` | HMAC-SHA256 |
| Instagram | `x-hub-signature-256` | HMAC-SHA256 |
| X (Twitter) | `x-twitter-webhooks-signature` | HMAC-SHA256 |
| Telegram | `x-telegram-bot-api-secret-token` | Secret token |
| WhatsApp | `x-hub-signature-256` | HMAC-SHA256 |
| LinkedIn | `x-linkedin-signature` | HMAC-SHA256 |

## Signature Verification

### Process

1. Platform sends webhook with signature header
2. API looks up active channel for platform
3. Retrieves channel's `webhook_secret`
4. Verifies signature matches payload
5. Rejects with 403 if verification fails

### Configuration

Each channel must have a `webhook_secret` configured:

```python
# When creating channel
channel = Channel(
    platform="facebook",
    webhook_secret="your-webhook-secret-here",
    ...
)
```

### Verification Code (Reference)

```python
async def verify_webhook_signature(platform: str, body: bytes, signature: str, channel: Channel) -> bool:
    secret = channel.webhook_secret
    if not secret:
        return False
    
    if platform in ["facebook", "instagram", "whatsapp"]:
        # HMAC-SHA256
        expected = "sha256=" + hmac.new(
            secret.encode(), body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)
    
    elif platform == "x":
        # Twitter uses HMAC-SHA256 with different format
        expected = "sha256=" + hmac.new(
            secret.encode(), body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)
    
    elif platform == "telegram":
        # Simple token comparison
        return hmac.compare_digest(secret, signature)
    
    elif platform == "linkedin":
        # LinkedIn uses HMAC-SHA256
        expected = hmac.new(
            secret.encode(), body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)
    
    return False
```

## Payload Limits

- **Max body size**: 1 MB (1,000,000 bytes)
- **Content-Length** header checked first
- Actual body size verified after reading
- Returns **413 Payload Too Large** if exceeded

## Response Requirements

### Success
- Return **2xx** within **10 seconds**
- Body: `{"status": "ok"}` (any valid JSON)

### Failure
- **4xx/5xx** = retry with exponential backoff
- **Timeout** = retry

### Retry Policy (Platform Dependent)

| Platform | Retries | Backoff |
|----------|---------|---------|
| Facebook/Instagram | Multiple | Exponential |
| X (Twitter) | Multiple | Exponential |
| Telegram | Multiple | Fixed |
| WhatsApp | Multiple | Exponential |
| LinkedIn | Multiple | Exponential |

## Event Types

### Google Reviews (via Channels)

Received via `POST /api/v1/channels/webhook/google_reviews` (OAuth notifications)

```json
{
  "notificationType": "REVIEW",
  "review": {
    "name": "accounts/123/locations/456/reviews/789",
    "reviewId": "789",
    "reviewer": {
      "profilePhotoUrl": "https://...",
      "displayName": "John Doe",
      "isAnonymous": false
    },
    "starRating": "FIVE",
    "comment": "Great service!",
    "createTime": "2024-01-15T10:30:00Z",
    "updateTime": "2024-01-15T10:30:00Z"
  }
}
```

### Facebook/Instagram

```json
{
  "object": "page",
  "entry": [
    {
      "id": "PAGE_ID",
      "time": 1705315800,
      "changes": [
        {
          "field": "reviews",
          "value": {
            "review_id": "123",
            "rating": 5,
            "review_text": "Amazing!",
            "reviewer_name": "Jane Smith",
            "created_time": 1705315800
          }
        }
      ]
    }
  ]
}
```

### X (Twitter)

```json
{
  "tweet_create_events": [
    {
      "id": "1234567890",
      "text": "@business Great product!",
      "user": {
        "id": "987654321",
        "name": "John Doe",
        "screen_name": "johndoe"
      },
      "created_at": "Mon Jan 15 10:30:00 +0000 2024"
    }
  ]
}
```

## Registering Webhooks

### Google Business Profile

1. Connect channel via OAuth (`/api/v1/channels/google/connect`)
2. Google sends notifications to registered webhook URL
3. Webhook URL: `https://api.sayvors.com/api/v1/channels/webhook/google_reviews`

### Facebook/Instagram

1. Create Facebook App
2. Add Webhooks product
3. Subscribe to `page` fields: `reviews`, `messages`
4. Callback URL: `https://api.sayvors.com/api/v1/channels/webhook/facebook`
5. Verify token: Set in channel `webhook_secret`

### X (Twitter)

1. Create Twitter App
2. Enable Account Activity API (AAAPI)
3. Register webhook: `POST /1.1/account_activity/all/{env}/webhooks.json`
4. URL: `https://api.sayvors.com/api/v1/channels/webhook/x`
5. CRC check handled automatically

### Telegram

1. Create bot via @BotFather
2. Set webhook: `https://api.telegram.org/bot<token>/setWebhook`
3. URL: `https://api.sayvors.com/api/v1/channels/webhook/telegram`
4. Secret token: Set in channel `webhook_secret`

### WhatsApp (via Meta)

1. Facebook Business Manager
2. WhatsApp Business API
3. Configure webhook in app dashboard
4. Callback URL: `https://api.sayvors.com/api/v1/channels/webhook/whatsapp`
5. Verify token: Set in channel `webhook_secret`

## Testing Webhooks

### Local Development (ngrok)

```bash
# Start ngrok
ngrok http 8000

# Use ngrok URL for webhook registration
# e.g., https://abc123.ngrok.io/api/v1/channels/webhook/facebook
```

### Manual Testing (cURL)

```bash
# Facebook-style webhook
curl -X POST http://localhost:8000/api/v1/channels/webhook/facebook \
  -H "Content-Type: application/json" \
  -H "x-hub-signature-256: sha256=..." \
  -d '{"object":"page","entry":[{"id":"123","time":1705315800,"changes":[{"field":"reviews","value":{"review_id":"456","rating":5,"review_text":"Test","reviewer_name":"Test User","created_time":1705315800}}]}]'
```

### Generate Test Signature

```python
import hmac
import hashlib

secret = "your-webhook-secret"
payload = b'{"test": "data"}'

signature = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
print(signature)
```

## Security Best Practices

1. **Always verify signatures** - Never process unverified webhooks
2. **Use HTTPS** - Webhook URLs must be HTTPS in production
3. **Rotate secrets** - Periodically update `webhook_secret`
4. **Validate payload structure** - Check required fields before processing
5. **Idempotency** - Handle duplicate deliveries (use event IDs)
6. **Rate limit webhooks** - Per-platform limits configured
7. **Log all webhooks** - For debugging and audit trail

## Monitoring

### Key Metrics

- Webhook received count (per platform)
- Signature verification failures
- Processing latency
- Error rates
- Retry counts

### Alerting

- Alert on > 1% signature failures
- Alert on processing latency > 5s
- Alert on webhook endpoint returning 5xx

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| 403 Invalid Signature | Wrong secret | Verify `webhook_secret` matches platform config |
| 413 Payload Too Large | Body > 1MB | Platform sending oversized payload |
| 404 Channel Not Found | No active channel | Ensure channel connected and active |
| Timeout | Processing > 10s | Move heavy processing to background worker |

### Debugging

```python
# Enable webhook debug logging
import logging
logging.getLogger("app.modules.channels.router").setLevel(logging.DEBUG)
```

Check logs for:
- `Webhook signature verification failed for platform=X`
- `Webhook received for platform=X with no active channel`
- `Payload too large`