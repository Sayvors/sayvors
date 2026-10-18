# API Configuration

The API reads settings from environment variables using
[`services/api/app/config.py`](../../services/api/app/config.py). Local
development settings belong in `services/api/.env`; use
[`services/api/.env.example`](../../services/api/.env.example) as the safe
starting template. Do not copy credentials from another developer's `.env`,
commit secrets, or put server-only credentials in a `NEXT_PUBLIC_` variable.

Pydantic parses list and mapping values from JSON, for example:

```dotenv
ALLOWED_HOSTS=["localhost","127.0.0.1"]
CORS_ORIGINS=["http://localhost:3000"]
```

Values below are application defaults, not recommended production secrets.
The runtime environment can override them.

## Core services and runtime

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | Local PostgreSQL URL | Primary database connection. |
| `DATABASE_READER_URL` | Empty | Optional read-replica URL; empty uses `DATABASE_URL`. |
| `DB_POOL_MODE` | `session` | PgBouncer mode (`session` or `transaction`). |
| `DB_POOL_SIZE` | `50` | SQLAlchemy async pool size. |
| `DB_POOL_MAX_OVERFLOW` | `50` | Additional connections above pool size. |
| `DB_POOL_TIMEOUT_SECONDS` | `30` | Seconds to wait for a pool connection. |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection. |
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | Kafka bootstrap server list. |
| `ENVIRONMENT` | `development` | Runtime environment; `production` enables fail-closed validation. |
| `VERSION` | `0.1.0` | Release identifier used in logs and error reporting. |
| `RUN_BACKGROUND_WORKERS` | `true` | Run queue and polling workers in the API process. Set false when using the dedicated worker service. |
| `LOG_FORMAT` | Automatic | `console`, `json`, or empty for automatic TTY-aware selection. |

## Authentication, cookies, and HTTP origins

| Variable | Default | Purpose |
|----------|---------|---------|
| `JWT_SECRET` | Unsafe placeholder; must be replaced | Signing secret. Startup exits if the placeholder remains; production requires at least 32 characters. Generate a random value with `python -c "import secrets; print(secrets.token_urlsafe(64))"`. |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm. |
| `JWT_ACCESS_EXPIRATION_MINUTES` | `15` | Access-token lifetime. |
| `JWT_REFRESH_EXPIRATION_DAYS` | `7` | Refresh-token lifetime. |
| `MAX_LOGIN_ATTEMPTS` | `5` | Failed login attempts before lockout. |
| `LOCKOUT_MINUTES` | `15` | Login lockout duration. |
| `AUTH_RATE_LIMIT_FAIL_CLOSED` | `true` | Reject auth-critical operations when Redis rate limiting is unavailable. Keep enabled outside isolated local development. |
| `TRUSTED_PROXIES` | `127.0.0.1`, `::1` | Proxy IPs/CIDRs whose forwarded client-IP headers are trusted. |
| `ALLOWED_HOSTS` | `localhost`, `127.0.0.1` | Accepted HTTP hostnames; production requires explicit hosts, not `*`. |
| `CORS_ORIGINS` | `http://localhost:3000` | Exact browser origins allowed by CORS. |
| `CORS_ORIGIN_REGEX` | Empty | Optional regex for dynamic development origins such as rotating tunnels. |
| `COOKIE_DOMAIN` | `.sayvors.com` | Shared cookie domain. Set empty for host-only local-development cookies. |
| `COOKIE_SECURE` | `true` | Mark cookies Secure. Keep true on HTTPS deployments; local plain-HTTP development needs false. |
| `COOKIE_SAMESITE` | `none` | Cookie SameSite policy: `none`, `lax`, or `strict`. `none` requires Secure in browsers. |
| `CSRF_COOKIE_NAME` | `csrf_token` | CSRF cookie name. |
| `ACCESS_COOKIE_NAME` | `access_token` | Access cookie name. |
| `REFRESH_COOKIE_NAME` | `refresh_token` | Refresh cookie name. |
| `ACCESS_COOKIE_MAX_AGE` | `900` seconds | Access cookie lifetime. |
| `REFRESH_COOKIE_MAX_AGE` | `604800` seconds | Refresh cookie lifetime. |
| `RETENTION_CLEANUP_INTERVAL_SECONDS` | `21600` | Interval for auth-record retention cleanup. |
| `RETENTION_DELETE_BATCH_SIZE` | `1000` | Maximum records deleted per cleanup batch. |

For split-domain browser deployments, configure the frontend origin in
`CORS_ORIGINS`, the API and web hosts in `ALLOWED_HOSTS`, and cookie domain,
Secure, and SameSite values to match the deployment's HTTPS/domain topology.
See [authentication](authentication.md) for the request and CSRF flow.

## Uploads and object storage

| Variable | Default | Purpose |
|----------|---------|---------|
| `UPLOAD_DIR` | `./data/uploads` | Local upload root. |
| `MAX_UPLOAD_SIZE_MB` | `100` | General upload size limit. |
| `MEDIA_DIR` | `./data/uploads/media` | Local public-media directory. |
| `MEDIA_PUBLIC_PATH` | `/media-files` | Public URL path for uploaded media. |
| `MEDIA_MAX_MB` | `25` | Media upload size limit. |
| `GCS_PUBLIC_BUCKET` | Empty | Optional public-media bucket. |
| `GCS_PRIVATE_BUCKET` | Empty | Optional private-document bucket. |
| `AWS_S3_BUCKET` | Empty | Optional shared S3 bucket fallback. |
| `S3_MEDIA_BUCKET` | Empty | S3 bucket override for public media. |
| `S3_DOCS_BUCKET` | Empty | S3 bucket override for private documents. |
| `AWS_REGION` | `eu-north-1` | AWS region. |
| `AWS_S3_ENDPOINT_URL` | Empty | Optional S3-compatible endpoint. |
| `S3_MEDIA_PUBLIC_BASE_URL` | Empty | Optional CDN/custom public-media base URL. |

Empty bucket settings use local storage. Configure cloud credentials through
the deployment's secret mechanism (for example, a mounted service-account file
for GCS); never commit credential files. Public media and private documents
must use appropriately separated storage/access policies.

## Encryption, email, and error reporting

| Variable | Default | Purpose |
|----------|---------|---------|
| `CHANNEL_ENCRYPTION_KEY` | Empty | Encryption key for stored channel credentials. Empty falls back to `JWT_SECRET` in development; set a separate key explicitly in production. |
| `RESEND_API_KEY` | Empty | Server-side Resend credential. |
| `RESEND_URL` | Resend email API URL | Resend endpoint override. |
| `RESEND_FROM` | Sayvors noreply sender | Display-name email sender. |
| `EMAIL_FROM` | `noreply@sayvors.com` | Default email sender address. |
| `FRONTEND_URL` | `http://localhost:3000` | Frontend base URL used in email links. |
| `EMAIL_SEND_ALLOW_ANY_RECIPIENT` | `false` | Permit arbitrary recipients for self-hosted relays; production startup rejects true. |
| `GLITCHTIP_DSN` | Empty | Server-side error-reporting DSN. |
| `GLITCHTIP_SECRET_KEY` | Empty | Optional server-side GlitchTip integration secret. |

## Google Business Profile and Localith

| Variable | Default | Purpose |
|----------|---------|---------|
| `GOOGLE_CLIENT_ID` | Empty | Google OAuth client ID for Business Profile reviews. |
| `GOOGLE_CLIENT_SECRET` | Empty | Google OAuth client secret; server-side only. |
| `GOOGLE_REVIEWS_REDIRECT_URI` | Local callback URL | OAuth redirect URI registered with Google. |
| `GOOGLE_REVIEWS_MOCK` | `false` | Use generated review data instead of live OAuth/provider data. |
| `GOOGLE_REVIEWS_POLL_INTERVAL_SECONDS` | `300` | Review polling interval. |
| `LOCALITH_API_KEY` | Empty | EmbedSocial/Localith API key. |
| `LOCALITH_BASE_URL` | `https://embedsocial.com/app/api` | Localith API base URL. |
| `LOCALITH_ITEMS_PATH` | `rest/v1/items` | Localith items endpoint path. |
| `BUSINESS_DATA_PROVIDER` | `localith` | Selected business-data provider. |
| `LOCALITH_SYNC_INTERVAL_SECONDS` | `60` | Background Localith sync interval. |
| `ANALYTICS_PERFORMANCE_SYNC_INTERVAL_SECONDS` | `21600` | Google performance metrics sync interval. |
| `ANALYTICS_PERFORMANCE_DAYS_BACK` | `30` | Days of historical performance metrics requested per sync. |
| `MESSAGING_ROLLUP_INTERVAL_SECONDS` | `900` | Messaging metrics rollup interval. |
| `POSTS_PUBLISH_INTERVAL_SECONDS` | `300` | Scheduled post publishing interval. |
| `MEDIA_PUBLISH_INTERVAL_SECONDS` | `300` | Scheduled media publishing interval. |

## Meta integrations

| Variable | Default | Purpose |
|----------|---------|---------|
| `META_APP_ID` | Empty | Meta app ID used for provider integrations. |
| `META_APP_SECRET` | Empty | Meta app secret; server-side only. |
| `META_LOGIN_APP_ID` | Empty | Optional dedicated Facebook sign-in app ID; falls back to `META_APP_ID`. |
| `META_LOGIN_APP_SECRET` | Empty | Optional dedicated Facebook sign-in secret; falls back to `META_APP_SECRET`. |
| `META_GRAPH_API_VERSION` | `v26.0` | Meta Graph API version. |
| `META_OAUTH_REDIRECT_URI` | Local API callback | Meta OAuth callback registered with Meta. |
| `META_WEBHOOK_VERIFY_TOKEN` | Empty | Shared secret used to verify Meta webhook setup. |
| `META_WHATSAPP_CONFIG_ID` | Empty | WhatsApp Embedded Signup configuration. |
| `META_WHATSAPP_COEXISTENCE_CONFIG_ID` | Empty | Separate Embedded Signup configuration for WhatsApp Coexistence. |
| `META_SOLUTION_ID` | Empty | Meta Tech Provider solution ID, when required by the onboarding flow. |
| `META_FACEBOOK_CONFIG_ID` | Empty | Facebook Login for Business configuration. |
| `META_INSTAGRAM_CONFIG_ID` | Empty | Instagram Login for Business configuration. |
| `PLAN_MESSAGE_LIMITS` | `{"free":1000,"pro":25000}` | Per-plan Sayvors messaging limits. |

Create separate Meta configuration IDs for WhatsApp, Facebook, and Instagram
as required by their respective flows. Configure the webhook callback as
`https://<api-host>/api/v1/meta/webhooks`. Setup details are in the
[Meta guides](../integrations/meta/architecture.md).

## Platform-admin settings

| Variable | Default | Purpose |
|----------|---------|---------|
| `ADMIN_PASSWORD_HASH` | Empty (admin API disabled) | Bcrypt hash for the separate platform-admin login. Set intentionally to enable the admin app. Generate a hash locally; do not put the plaintext password in configuration. |
| `ADMIN_SESSION_MINUTES` | `120` | Platform-admin session lifetime. |
| `ADMIN_MAX_CONSECUTIVE_FAILURES` | `10` | Global failed-login lockout threshold. |
| `ADMIN_COOKIE_NAME` | `sayvors_admin_token` | Name of the httpOnly admin session cookie. |

## Worker-only settings

These are consumed outside the main `Settings` class:

| Variable | Default | Purpose |
|----------|---------|---------|
| `WORKER_LOOPS` | Empty (all enabled loops) | Optional comma-separated worker loop selection for the dedicated worker process. |
| `LEAD_DIGEST_POLL_SECONDS` | `3600` | Lead digest worker polling interval. |
| `META_EVENTS_POLL_SECONDS` | `5` | Meta event worker polling interval. |
| `META_EVENTS_BATCH_SIZE` | `20` | Maximum Meta events claimed per batch. |
| `META_EVENTS_CONCURRENCY` | `8` | Concurrent Meta event handlers. |
| `META_EVENTS_LEASE_SECONDS` | `120` | Event-claim lease duration. |
| `META_EVENTS_MAX_RETRIES` | `5` | Maximum event processing retries. |
| `META_EVENTS_RETRY_BASE_SECONDS` | `300` | Initial retry delay. |
| `META_EVENTS_RETRY_MAX_SECONDS` | `7200` | Maximum retry delay. |

## Test and security-sensitive switches

| Variable | Default | Purpose |
|----------|---------|---------|
| `TESTING` | `false` | Test-only behavior gate; do not enable in a deployed environment. |
| `RAG_DB_ALLOW_PRIVATE_HOSTS` | `false` | Permit RAG live-database connections to private networks. Production startup rejects true because of SSRF risk. |

LLM provider keys are stored in the database and managed through the platform
admin UI; they are not read from API environment variables.
