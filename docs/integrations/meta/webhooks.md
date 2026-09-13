# Meta Integration — Webhooks

Central ingress (one callback URL per Meta app — required):

```
GET  /api/v1/meta/webhooks   handshake
POST /api/v1/meta/webhooks   event ingress
```

## Handshake

`GET ?hub.mode=subscribe&hub.challenge=…&hub.verify_token=…` → verify
`hub.mode == "subscribe"` and token equals `META_WEBHOOK_VERIFY_TOKEN`
(constant-time compare) → return `hub.challenge` as plain text, else 403.
Requires HTTPS with a valid cert.

## Ingress pipeline (must return 200 fast)

1. Size cap (1 MB, same as channels webhooks).
2. Signature: `X-Hub-Signature-256: sha256=<hex>` =
   `HMAC-SHA256(raw_body, META_APP_SECRET)`. Compare hex **after** the
   `sha256=` prefix, on raw bytes (never re-serialized JSON). Reject → 403.
   (Note: legacy `channels/service.py` verifier doesn't strip the prefix —
   the Meta verifier is intentionally separate.)
3. Parse `object`: `whatsapp_business_account` → WhatsApp parser,
   `page` → Facebook parser, `instagram` → Instagram parser.
4. Asset lookup by external id (phone_number_id / page id / IG id) →
   tenant + connection resolution from `meta_assets`. Unknown asset → store
   as `unresolved`, 200 (don't make Meta retry garbage forever — log it).
5. Persist `meta_webhook_events` row. Unique
   `(provider, external_event_id, event_type)` → duplicates become
   `duplicate`, never processed twice (replay-safe).
6. Enqueue normalized event on the outbox (`meta-events` topic) → 200.

## Normalized envelope (what the rest of Sayvors sees)

```json
{
  "event_id": "...", "tenant_id": "...", "connection_id": "...",
  "provider": "whatsapp", "event_type": "message.received",
  "external_asset_id": "...", "external_event_id": "...",
  "occurred_at": "...", "payload": {...}
}
```

Event types: `message.received`, `message.status`, `comment.received`,
`account.update`, … Provider parsers map raw shapes to these; business
logic (Phase 2) only consumes normalized events.

## Subscriptions to configure

- WhatsApp: `messages` + `account_update` fields; per-customer
  `POST /{WABA_ID}/subscribed_apps`.
- Facebook: `feed` (+ `messages` for Messenger) at app level and
  `POST /{page-id}/subscribed_apps {subscribed_fields}` per Page.
- Instagram: `comments`, `messages`, … per the fields table for the chosen
  login stack.

## Retention / audit

Raw payloads retained per data-retention policy; structured logs for
received/rejected/processed/duplicate. Never log secrets.
