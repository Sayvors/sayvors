# Billing and Notifications

This guide describes the current customer-app workflows. API paths and
request-level details are in the [endpoint reference](../api/endpoints.md).

## Billing

Open **Dashboard → Billing** to see the current plan and AI-credit balance,
edit billing details, and manage saved payment methods. The account's plan and
credit grants are managed by platform operations; customers should contact
support for plan changes or credit top-ups.

### Free trial

Every new tenant starts on the **Free Trial** plan with **$10 of AI credit**.
The credit is granted once per tenant at signup through the durable ledger
(`TRIAL_CREDIT_CENTS`, default `1000`). The trial stays active until the tenant
moves to another plan; there is no countdown and no automatic downgrade.

Accounts created before the trial grant shipped can be backfilled:

```bash
python -m scripts.backfill_trial_credits --email user@example.com --apply
```

Omit `--email` to grant every eligible zero-credit tenant. Without `--apply`
the script is a dry run.

### Plans page

- **Free Trial** is the entry plan; it includes $10 of AI credit.
- **Starter, Pro and Growth** are shown for comparison but are disabled until a
  real payment gateway is connected. The app must never show a fake “pay”
  button or activate a paid plan without a payment.
- **Enterprise** is custom: the button opens an email to `it@sayvors.com` instead of showing a
  price or charging a card.
- There is **no downgrade action** in the UI. Current plans show
  “Your current plan” and are disabled.
- Starting a paid plan is an operator action until checkout is implemented
  (`POST /api/v1/admin/tenants/{id}/plan` writes the plan, wallet and ledger).

### Billing details

Save the billing name and supported billing address/tax fields from the Billing
page. The billing email is the account email and is displayed as read-only.

### Saved cards and important limitation

Cards can be added, selected as the default, or removed. The current UI sends
card metadata to Sayvors' stub tokenization route: brand, last four digits,
expiry, and optional cardholder name. The full card number is not sent to the
API; the UI validates it locally and the stub returns a token. Saved cards are
marked unverified until a real gateway integration is available.

### Messaging quota vs. AI auto-replies

Sayvors has two separate caps on outbound messages, and they are intentional:

**Messaging quota** (`PLAN_MESSAGE_LIMITS`, e.g. free: 1,000 / month) governs
human-initiated sends (`/inbox/send`, document, location, contacts, template).
Every human outbound message passes through `_ensure_messaging_quota()` and is
counted against the plan's `max_messages_per_month`.

**AI auto-replies** (`meta/consumer.py` reply path) do **not** count against the
messaging quota. They are bounded instead by the **LLM budget gate**:
`check_feature(tenant_id, "ai_replies")` (fail-closed entitlement — the plan must
enable AI replies) plus credit reserve/settle before every LLM call
(`billing/entitlements.py`, `llm/gateway.py`). AI replies are also selectively
triggered by `should_ai_reply()` (confusion detection, mode state, escalation
clock), so not every inbound message generates one.

**Decision:** AI auto-replies remain unbounded by `max_messages_per_month`. The
LLM budget gate is the appropriate control for AI usage because it directly caps
dollar cost (tokens), whereas the messaging quota caps human conversation
volume. Extending the messaging quota to AI replies would double-count cost
control and add latency to the hot reply path without reducing spend.

If you want AI replies to also consume messaging quota, extend
`_ensure_messaging_quota()` (or `count_messages_this_month()`) to include
AI-authored outbound rows and call it from the `meta/consumer.py` reply path
before `adapter.send_text_message()`.

**Payments are not live yet.** The current charge endpoint is a stub and moves
no money; adding a card does not charge it, create a subscription, or add
credits. The page's plan/credit display reflects the account state provided by
the API, not a completed payment.

## Notifications

- Filter by **All** or **Unread**, and by **Syncs**, **Reviews**, or **Replies**.
- Select a notification to mark it read and follow its destination link, when
  one is provided.
- Use **Mark all read** to clear the unread state across the feed.
- Load older items by paging through the feed.

The category tabs count sync events, review events, and reply outcomes.
Other event types (for example review tickets) can still appear in the overall
feed under **All**.

### Live popup preferences

The **Live popups** settings control in-app alerts for **New messages**,
**Qualified leads**, and **Review tickets**. These toggles affect live popup
delivery; they do not remove or filter saved notification-feed items.
Preferences are saved to the workspace/account settings through
`PATCH /api/v1/notifications/settings`.

Notification list and read operations require the `notifications.view`
permission. The current notification preference settings are the three popup
toggles above; they are not per-category email subscriptions.
