# Meta Integration — Architecture

Multi-tenant Meta subsystem for Sayvors: each tenant connects and manages
**their own** Meta assets (WABA + phone number, Facebook Page, Instagram
business account). Sayvors never uses one shared Meta account for all tenants.

Code: `services/api/app/modules/channels/meta/`

```
MetaIntegrationService (service.py)
├── providers/base.py          MetaProviderAdapter ABC
├── providers/whatsapp.py      WhatsAppAdapter (Embedded Signup v4, Cloud API)
├── providers/facebook.py      FacebookAdapter (Login for Business, Pages API)
├── providers/instagram.py     InstagramAdapter (FB-Login stack, via Page)
├── credentials.py             Fernet encrypt/decrypt + redaction (server-side only)
├── oauth.py                   state + transaction lifecycle (server-side rows)
├── capabilities.py            table-driven scopes per provider/capability
└── webhooks/                  central ingress: router, verifier, parser, normalizer
```

## Principles

- **One generic subsystem, thin adapters.** Routers call services; services
  call adapters. No provider logic in routers.
- **Existing `channels` architecture untouched.** New tables (`meta_*`),
  new router (`/api/v1/meta`), new webhook ingress (`/api/v1/meta/webhooks`).
  The legacy `POST /api/v1/channels/webhook/{platform}` stub is left alone.
  Per active messaging asset we also create a `Channel(platform=whatsapp|…)`
  row so inbox/auto-reply UI keeps working without rewrites.
- **Central webhook ingress is mandatory**, not just tidy: Meta allows one
  callback URL per app. `object` (`whatsapp_business_account|page|instagram`)
  selects the parser; external asset id resolves the tenant from our DB.
- **Webhooks are fast**: verify → persist raw → enqueue → 200. AI work happens
  in consumers (Phase 2), never in the request path.

## Data model

- `meta_connections` — one row per (tenant, provider) connection: encrypted
  token, expiry, scopes, status, health timestamps.
- `meta_assets` — provider assets (WABA, phone_number, page, ig_account);
  `parent_asset_id` models Page→IG→Portfolio linkage.
- `meta_oauth_transactions` — server-side state rows: hash, tenant binding,
  one-time use, 10-min expiry.
- `meta_webhook_events` — raw payload retention + idempotency via unique
  `(provider, external_event_id, event_type)`.

## Tenant isolation

Every row carries `tenant_id`; every query filters by it. Cross-tenant tests
in `tests/test_meta_isolation.py` prove a tenant cannot read/use another
tenant's connections, assets, or credentials.

## Connection health

`active | needs_reauth | expired | revoked | error`, plus
`last_validated_at`, `last_successful_api_call_at`,
`last_webhook_received_at`. Surfaced per connection; `POST
/api/v1/meta/{provider}/validate` re-checks on demand.

## Observability

Structured logs for oauth started/completed/failed, asset
discovered/connected/disconnected, token validation failed, webhook
received/rejected/processed/duplicate, Meta API failures. Never log tokens,
secrets, or Authorization headers (`credentials.redact`).

## API versioning

Single constant: `META_GRAPH_API_VERSION` (default `v26.0`) in
`providers/base.py`, from env. No version strings scattered in code.
Verify against the Meta app dashboard + changelog when upgrading.

## Phasing

- **Phase 1 (this build):** abstraction, tenant isolation, OAuth/state,
  WhatsApp Embedded Signup, FB Login for Business, Instagram connection,
  central webhook ingress, normalization, credential storage, health, tests.
- **Phase 2:** messaging actions + AI automation on normalized events.
- **Phase 3:** publishing, analytics, more capabilities.
