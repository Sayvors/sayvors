# Meta WhatsApp spend attribution

## Sources and truth boundaries

Sayvors records outbound attempts in PostgreSQL for quota enforcement. Meta
`pricing_analytics` is authoritative for **approximate delivered spend**; the
deprecated `conversation_analytics` field is not used for cost. Local message
rows are never converted into currency and no missing Meta cost is estimated.

The daily worker refreshes a rolling seven-day UTC window for active WABA assets.
It uses DAILY granularity, COUNTRY/PHONE/PRICING_CATEGORY/PRICING_TYPE/TIER
dimensions, and COST+VOLUME. Pages are keyset-bounded, provider concurrency is
capped, and retries use bounded exponential backoff. Access tokens are used only
in the Graph Authorization header and are never logged or returned by an API.

## Spend facts

`whatsapp_spend_daily` stores one fact per tenant/WABA/date/full attribution
hash. The hash includes Messaging account ID (when available), phone, country,
pricing category, pricing type, and tier. Rolling retries replace volume/cost in
place, so Meta adjustments do not duplicate spend.

Missing/null cost is stored as SQL NULL with `cost_status='unavailable'`; zero is
stored only when Meta reports zero. Native currency, WABA timezone, and funding
mode are retained. Funding modes are `direct_client`, `shared_credit_line`,
`platform_liable`, or internal `unknown`. API presentation conservatively maps
unknown liability to client-direct so it cannot enter Sayvors-payable totals.
Costs are grouped by native currency and funding mode; unlike currencies are
never summed. Only `platform_liable` facts are Sayvors COGS.

Status webhooks retain `billable`, `pricing_model`, category/type/subtype. A
`sent` status on a stored outbound row confirms reconciliation without adding a
second quota count.

## Quota arbitration

Every WhatsApp Cloud API `POST /{phone_number_id}/messages` call passes through
`WhatsAppAdapter._graph`. Typing/read indicators are excluded; text, templates,
media, cards, reactions, interactive messages, status posts, AI parts, and bulk
deliveries are included. The adapter resolves the active phone asset's tenant,
then atomically:

1. inserts/locks the tenant/month usage row;
2. returns an existing idempotent reservation or checks the effective plan limit
   (base allowance plus additive bonuses);
3. inserts the reservation and increments the counter in one transaction.

PostgreSQL `SELECT ... FOR UPDATE` serializes concurrent workers. Redis is not a
quota authority. Stable keys cover manual rows, templates, lead actions, review
requests, and each AI part; quoted AI retries derive a stable payload hash.

Provider success consumes a reservation. Meta HTTP errors and ambiguous
mid-flight failures remain charged because they may have reached Meta. Only
`MetaTransportError` (proven connect-phase failure) releases and decrements,
exactly once. The pre-existing monthly count falls back to legacy rows only when
no reservation counter exists, preserving compatibility without ignoring
released pre-send failures.

## APIs

- `GET /api/v1/billing/whatsapp-usage?days=30|90|365` is tenant-scoped and returns
  local used/limit/remaining plus native-currency/funding totals and WABA, phone,
  and category breakdowns.
- `GET /api/v1/admin/whatsapp-spend?days=30|90|365` requires the separate admin
  gate and returns per-tenant/WABA rows plus authoritative totals.

Responses expose no token or raw provider payload. Null cost remains null;
cost availability and sync status are explicit. Tenant top-level cost is a safe
primary total, never a cross-currency sum.
