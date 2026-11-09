# Google Reviews Push Setup (Pub/Sub) — Runbook

One-time setup per Google Cloud project + per connected Business Profile
account. After it, reviews reach the dashboard in seconds instead of ≤60s
(poll) — with the poll and the daily sweep still running as the guarantee
layers.

## Prerequisites

- A Google Cloud project with Cloud Pub/Sub enabled.
- The OAuth client used for Business Profile connections
  (`GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`) — merchant tokens stored on
  the channel rows already carry the `business.manage` scope this needs.
- The deployment's public API base URL (the push subscription must reach
  `POST /api/v1/channels/google/pubsub` over HTTPS).

## 1. Create the topic and grant Google publish rights

```bash
gcloud pubsub topics create sayvors-gbp-events

# Google's Business Profile notification publisher must be able to publish.
gcloud pubsub topics add-iam-policy-binding sayvors-gbp-events \
  --member="serviceAccount:mybusiness-api-pubsub@system.gserviceaccount.com" \
  --role="roles/pubsub.publisher"
```

## 2. Create a service account for the push subscription's OIDC tokens

The push subscription signs each delivery with an OIDC token minted for a
service account you own — that identity is what the API pins.

```bash
gcloud iam service-accounts create sayvors-gbp-push \
  --display-name="GBP push delivery identity"
```

## 3. Create the push subscription

```bash
gcloud pubsub subscriptions create sayvors-gbp-push-sub \
  --topic=sayvors-gbp-events \
  --push-endpoint="https://<your-api-host>/api/v1/channels/google/pubsub" \
  --push-auth-service-account="sayvors-gbp-push@<project>.iam.gserviceaccount.com" \
  --push-auth-audience="sayvors-gbp-push" \
  --ack-deadline=60
```

- `--push-auth-audience` must equal `GOOGLE_PUBSUB_PUSH_AUDIENCE` in the
  API env — the endpoint rejects any other audience.
- `--ack-deadline=60` gives a slow pull room; the endpoint acks fast
  anyway, and duplicate delivery is safe.

## 4. Configure the API env

```dotenv
GOOGLE_PUBSUB_PUSH_AUDIENCE=sayvors-gbp-push
GOOGLE_PUBSUB_PUSH_EMAIL=sayvors-gbp-push@<project>.iam.gserviceaccount.com
```

Empty audience = push ingress disabled (endpoint answers 503; polling
continues unchanged).

## 5. Register notifications on each connected Business Profile account

Notifications are an account-level setting, registered through the
**Notifications API** (`mybusinessnotifications.googleapis.com`, NOT
accountmanagement). The bundled script uses the merchant tokens already
stored on the channel rows — no re-auth:

```bash
cd services/api
python ../scripts/register_gbp_notifications.py \
  --topic projects/<project>/topics/sayvors-gbp-events   # dry-run: prints the PATCH
python ../scripts/register_gbp_notifications.py \
  --topic projects/<project>/topics/sayvors-gbp-events --apply
python ../scripts/register_gbp_notifications.py --check   # read current settings
```

Raw equivalent (one Google account, merchant access token with
`https://www.googleapis.com/auth/business.manage`):

```bash
curl -X PATCH \
  "https://mybusinessnotifications.googleapis.com/v1/accounts/{accountId}/notificationSetting?updateMask=notificationTypes,pubsubTopic" \
  -H "Authorization: Bearer <merchant access token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "accounts/{accountId}/notificationSetting", "notificationTypes": ["NEW_REVIEW", "UPDATED_REVIEW"], "pubsubTopic": "projects/<project>/topics/sayvors-gbp-events"}'
```

`GET .../notificationSetting` (same URL, no mask/body) reads the current
setting. Reviews now flow: Google → topic → push → targeted pull →
stored/drafted/published within seconds.

## Test locally in minutes (tunnel + a real review)

Local dev gets pushes through the existing cloudflared tunnel
(`dev-api.sayvors.com` → local API) — Google cannot reach `localhost`.

1. **Run the stack locally** (dev API runs the poll loop in-process):
   `python -m uvicorn app.main:app` from `services/api`, plus cloudflared
   with the dev-api tunnel config.
2. **Set the env** (step 4 values) and restart, so the endpoint is armed.
3. **Point the subscription at the tunnel**:
   `--push-endpoint="https://dev-api.sayvors.com/api/v1/channels/google/pubsub"`.
4. **Register notifications** (step 5 script — works against the local DB).
5. **Smoke-test the push chain without a review**:
   ```bash
   gcloud pubsub topics publish sayvors-gbp-events \
     --message='{"notificationType": "NEW_REVIEW", "location": "accounts/<acc>/locations/<loc>"}'
   ```
   Within seconds the API log must show
   `Google push … spawned_pulls=1` — that proves tunnel → endpoint →
   verification → targeted pull all work.
6. **Set the local channel to auto-publish** so the reply posts without a
   human click:
   ```bash
   curl -X PUT http://localhost:8000/api/v1/channels/<channel_id>/autoreply \
     -b cookies.txt -H "x-csrf-token: <csrf>" -H "Content-Type: application/json" \
     -d '{"approval_mode": "auto"}'
   ```
   (or the Channels page toggle in the dashboard).
7. **Real review test**: a customer posts a review on the connected
   listing → review appears in seconds (push); AI draft generates; with
   `auto` mode it publishes and passes read-back confirmation. If the
   push chain ever fails, the 60s poll still lands it ≤1 minute.

## Troubleshooting

| Symptom | Meaning |
|---|---|
| `Google push OIDC rejected` in logs | Audience/env mismatch, expired token, or the subscription's service account changed — recheck step 3/4. |
| `Google push rate limited` | Burst ceiling (600/min/IP) tripped — expected under outage-recovery replays; Pub/Sub retries. |
| `spawned_pulls=0` | No active channel has that `listing_key` — the location isn't connected, or the channel is expired/disconnected (reconnect it). |
| Pushes arrive but reviews lag | The targeted pull lost the claim race to the poll pass — harmless; the review lands on the next poll cycle. |
| 503 from the endpoint | `GOOGLE_PUBSUB_PUSH_AUDIENCE` unset in that deployment — set it or disable the subscription. |
| PATCH returns 400/403 on registration | Token lacks `business.manage`, or the publisher grant (step 1) is missing — Google's error text names which. |

## Related

- `docs/security/google-pubsub-webhook.md` — guard design + invariants
- `docs/operations/workers-and-jobs.md` — worker loop topology
