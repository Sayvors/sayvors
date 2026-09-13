# Meta Integration — WhatsApp (Cloud API, Tech Provider)

Production path: **Embedded Signup v4** (client onboarding), not manual
Graph API Explorer tokens. Sayvors acts as Tech Provider: the client adds
their own payment method; Meta bills the client.

## Tenant flow

```
Tenant → Connect → FB.login({config_id…}) → Meta onboarding
  → session: waba_id, phone_number_id, business_id, auth code
→ backend exchanges code → customer business token
→ POST /{WABA_ID}/subscribed_apps
→ POST /{PHONE_NUMBER_ID}/register {messaging_product:"whatsapp", pin}
→ persist WABA + phone_number assets + Channel(platform=whatsapp) row
→ test send → active
```

Relationship: Tenant → Client Business Portfolio → Client WABA →
Client Phone Number. Never assume one global WABA/number.

## Credentials per connection

`WABA_ID`, `phone_number_id`, customer-scoped business token (encrypted at
rest). Subscribe to the `account_update` field to learn new ids.

## Messaging rules (Phase 2 follows these)

- **24-hour customer-service window**: free-form text only within 24h of the
  user's last message; outside it, template messages only (templates need
  Meta pre-approval — Phase 2).
- Send: `POST /{PHONE_NUMBER_ID}/messages`.
- Inbound + statuses arrive on the central webhook (`messages[]`,
  `statuses[]`).

## Environment

`META_APP_ID`, `META_APP_SECRET`, `META_GRAPH_API_VERSION` (default `v26.0`),
`META_OAUTH_REDIRECT_URI`, `META_WEBHOOK_VERIFY_TOKEN`,
`META_WHATSAPP_CONFIG_ID` (Embedded Signup Builder configuration id).

## Tenant onboarding checklist

1. App Dashboard → WhatsApp → Embedded Signup Builder → configuration
   (60-day-expiration token template or custom) → `config_id`.
2. Allowed domains + Valid OAuth redirect URIs include Sayvors URLs (HTTPS).
3. Tech Provider onboarding + business verification.
4. App Review Advanced: `whatsapp_business_management` +
   `whatsapp_business_messaging` (+ screencasts) before external businesses.
5. Onboarding cap: 10 customers / rolling 7 days solo (200 multi-partner).

## Failure / recovery

- `needs_reauth`: token rejected → tenant reconnects (Embedded Signup again).
- Webhook gaps: statuses are informational; inbound dedupe by message id.
- Number re-register (PIN) if messaging shows as unregistered.
