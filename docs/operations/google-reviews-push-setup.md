# Google Reviews Push Setup (Pub/Sub) — Runbook

One-time setup per Google Cloud project + per connected account. After it,
reviews reach the dashboard in seconds instead of ≤60s (poll) — with the
poll and the daily sweep still running as the guarantee layers.

## Prerequisites

- A Google Cloud project with Cloud Pub/Sub enabled.
- The OAuth client used for Business Profile connections
  (`GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`).
- The deployment's public API base URL (the push subscription must reach
  `POST /api/v1/channels/google/pubsub` over HTTPS).

## 1. Create the topic and grant Google publish rights

```bash
gcloud pubsub topics create sayvors-gbp-events

# Google's Business Profile publisher service account needs the
# publisher role on the topic.
gcloud pubsub topics add-iam-policy-binding sayvors-gbp-events \
  --member="serviceAccount:mybusiness-api@system.gserviceaccount.com" \
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

Notifications are an account-level setting. Run once per merchant Google
account, authenticated as that account's OAuth credentials:

```bash
curl -X PATCH \
  "https://mybusinessaccountmanagement.googleapis.com/v1/accounts/{accountId}/notificationSetting" \
  -H "Authorization: Bearer <access token of the merchant>" \
  -H "Content-Type: application/json" \
  -d '{"notificationTypes": ["NEW_REVIEW", "UPDATED_REVIEW"], "pubsubTopic": "projects/<project>/topics/sayvors-gbp-events"}'
```

`GET .../notificationSetting` reads the current setting. New review
notifications now flow: Google → topic → push → targeted pull → review
stored/drafted/published within seconds.

## Verify end-to-end

1. Post a test review to a connected listing (or ask the merchant to).
2. API log should show, within seconds:
   `Google push <messageId> type=NEW_REVIEW locations=<locationId> spawned_pulls=1`
   followed by the usual poll pipeline logs for that channel.
3. Dashboard shows the review; with `approval_mode=auto` the reply posts
   and passes read-back confirmation.

## Troubleshooting

| Symptom | Meaning |
|---|---|
| `Google push OIDC rejected` in logs | Audience/env mismatch, expired token, or the subscription's service account changed — recheck step 3/4. |
| `Google push rate limited` | Burst ceiling (600/min/IP) tripped — expected under outage-recovery replays; Pub/Sub retries. |
| `spawned_pulls=0` | No active channel has that `listing_key` — the location isn't connected, or the channel is expired/disconnected (reconnect it). |
| Pushes arrive but reviews lag | The targeted pull lost the claim race to the poll pass — harmless; the review lands on the next poll cycle. |
| 503 from the endpoint | `GOOGLE_PUBSUB_PUSH_AUDIENCE` unset in that deployment — set it or disable the subscription. |

## Related

- `docs/security/google-pubsub-webhook.md` — guard design + invariants
- `docs/operations/workers-and-jobs.md` — worker loop topology
