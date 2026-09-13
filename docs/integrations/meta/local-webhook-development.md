# Meta Webhooks — Local Development (ngrok)

Forward real Meta (WhatsApp / Facebook / Instagram) webhook events to your
local Sayvors backend during development using an HTTPS tunnel.

> Requires an existing Meta app (App Dashboard → Meta for Developers) with
> `META_APP_ID`, `META_APP_SECRET`, webhook subscription, and — for WhatsApp —
> a test number or a connected WABA.

## How the ingress works (recap)

One callback URL per Meta app: `https://<your-domain>/api/v1/meta/webhooks`.

- `GET` — Meta handshake: `hub.mode=subscribe`, `hub.verify_token`,
  `hub.challenge`. Echoes the challenge, else 403.
- `POST` — event ingress: HMAC-SHA256 `X-Hub-Signature-256` checked against
  `META_APP_SECRET`, raw payload persisted to `meta_webhook_events`,
  normalized event enqueued on the outbox (`meta-events`). Returns `200`
  immediately — no AI runs synchronously (Phase 2 consumers process later).

The callback URL itself is **not read from app code**; you paste it into the
Meta Dashboard. `META_WEBHOOK_VERIFY_TOKEN` / `META_APP_SECRET` come from
your backend environment.

## Step 1 — Backend environment

Create `services/api/.env` from `.env.example` and set the Meta values:

```dotenv
META_APP_ID=1234567890123456
META_APP_SECRET=<your app secret from App Dashboard → App settings>
META_GRAPH_API_VERSION=v26.0
META_WEBHOOK_VERIFY_TOKEN=<any long random string you choose>
```

Do not commit these. `.env` is git-ignored.

Backend runs on port 8000 in `services/api`. If the API is already running
from another terminal, set the new vars there too, or just restart it.

## Step 2 — Allow the ngrok host

The API rejects unknown `Host` headers (`TrustedHostMiddleware`). Add your
ngrok domain to `ALLOWED_HOSTS` in `services/api/.env`:

```dotenv
ALLOWED_HOSTS=["localhost","127.0.0.1","<your-ngrok-subdomain>.ngrok-free.app"]
```

Otherwise Meta's delivery is rejected before it reaches the webhook router.

## Step 3 — Start the backend and the tunnel

Terminal 1 — FastAPI on port 8000:

```powershell
cd services/api
.venv\Scripts\uvicorn.exe app.main:app --reload --port 8000
```

Terminal 2 — tunnel:

```powershell
ngrok http 8000
```

Copy the HTTPS forwarding URL from the ngrok UI, e.g.
`https://a1b2c3d4e5f6.ngrok-free.app`.

## Step 4 — Callback URL

Construct:

```
https://<NGROK_DOMAIN>/api/v1/meta/webhooks
```

Example:

```
https://a1b2c3d4e5f6.ngrok-free.app/api/v1/meta/webhooks
```

Future production simply uses:

```
https://<PRODUCTION_API_DOMAIN>/api/v1/meta/webhooks
```

Same endpoint — only the domain changes.

## Step 5 — Meta Developer Dashboard

1. [developers.facebook.com/apps](https://developers.facebook.com/apps) →
   your app → **App settings → Basic**: confirm `META_APP_ID` and
   `META_APP_SECRET` match your `.env`.
2. **App settings → Advanced** (or *Webhooks* under the product you care
   about) → **Add callback URL**:
   - Callback URL: `https://<NGROK_DOMAIN>/api/v1/meta/webhooks`
   - Verify token: the exact `META_WEBHOOK_VERIFY_TOKEN` value
   - Click **Verify and save**. Meta calls your `GET` endpoint; if
     everything lines up it returns `200`, your `Verify token` is accepted,
     and Meta shows the field list you can subscribe to.
3. Subscribe to the fields you want (e.g. WhatsApp `messages`,
   `account_update`; Pages `feed`, `messages`; Instagram `comments`,
   `messages`).
4. Send a test webhook from the dashboard (per-product *Test* buttons) or
   use the real app (below).

## Step 6 — Verify the GET handshake manually

```powershell
Invoke-WebRequest -Uri "https://<NGROK_DOMAIN>/api/v1/meta/webhooks?hub.mode=subscribe&hub.verify_token=<TOKEN>&hub.challenge=12345" | Select-Object -ExpandProperty Content
```

Expect `12345` (the challenge echoed back) with HTTP 200. With a wrong
token you get `403 Forbidden`.

You can also curl the Localith/`localhost` variant to sanity-check before
involving ngrok:

```powershell
Invoke-WebRequest -Uri "http://localhost:8000/api/v1/meta/webhooks?hub.mode=subscribe&hub.verify_token=<TOKEN>&hub.challenge=12345" -Headers @{ "Host" = "localhost" }
```

## Step 7 — Send a real WhatsApp webhook

You need a connected phone number (a `meta_assets` row) so the event
resolves to a tenant:

1. Connect WhatsApp from the app UI (Channels → WhatsApp → Connect) — this
   creates `meta_connections`/`meta_assets` for your tenant.
2. From the Dashboard, open the WhatsApp product → **API Setup** (or
   **Webhooks → Test**). Pick the phone number and send yourself a message
   (e.g. "ping").
3. Meta POSTs to your ngrok callback URL.

## Step 8 — Expected logs

The backend logs (terminal 1) show:

```
INFO      Meta webhook handshake accepted
INFO      Meta webhook provider=whatsapp events=1
INFO      Meta webhook resolved tenant=<tenant-id> external=<phone_number_id>
INFO      Meta webhook duplicate provider=whatsapp event=wamid.XYZ   (only on replay)
WARNING   Meta webhook unresolved asset ...                          (if tenant unknown)
```

(Exact wording lives in `meta/webhooks/router.py`; check the current source
for the precise strings.)

## Step 9 — Confirm each pipeline stage

| Stage | How to confirm |
| --- | --- |
| Signature verified | No `403 Invalid signature` in logs; event accepted |
| Tenant resolved | Log line / `meta_webhook_events.tenant_id` not null |
| Raw event persisted | `SELECT * FROM meta_webhook_events WHERE external_event_id = '…'` |
| Normalized | Row's `event_type` in (`message.received`, `comment.received`, …) |
| Duplicate handling | Re-send the same payload → second delivery is `duplicate`, one row only |
| Outbox / Kafka event | `SELECT * FROM event_outbox WHERE topic = 'meta-events'` has the envelope |

## Inspecting the database (optional, via psql)

```sql
SELECT id, provider, external_event_id, event_type, tenant_id, status, created_at
FROM meta_webhook_events ORDER BY created_at DESC LIMIT 10;

SELECT id, event_type, topic, payload FROM event_outbox
WHERE topic = 'meta-events' ORDER BY id DESC LIMIT 5;
```

## Troubleshooting

- **400 Invalid host header** → `ALLOWED_HOSTS` is missing the ngrok domain
  (Step 2). It is a JSON array in `.env`.
- **403 on handshake** → `META_WEBHOOK_VERIFY_TOKEN` mismatch between `.env`
  and the Dashboard, or the token is empty. Restart uvicorn after changing
  `.env`.
- **403 on POST / Invalid signature** → `META_APP_SECRET` mismatch, or Meta
  is signed differently (see `X-Hub-Signature-256` header value — should be
  `sha256=<hex>`).
- **200 but no `event_outbox` row** → the phone number id is not in
  `meta_assets` yet (unresolved). Connect the channel first.
- **ngrok domain changed** → update `ALLOWED_HOSTS` and the Dashboard
  callback URL every run (free ngrok domains change). The helper script
  below prints the current URL.
- **Meta rejects the callback URL during verification** → the tunnel must be
  live when you click *Verify and save*; Meta calls your `GET` endpoint
  immediately.

## Optional: helper script

`scripts/meta-dev-webhook.ps1` starts ngrok on port 8000 and prints the
callback URL + verify-token hint. Requires `ngrok` on `PATH` (or set
`ngrokPath`). Run from the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/meta-dev-webhook.ps1
```