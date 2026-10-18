# Billing and Notifications

This guide describes the current customer-app workflows. API paths and
request-level details are in the [endpoint reference](../api/endpoints.md).

## Billing

Open **Dashboard → Billing** to see the current plan and AI-credit balance,
edit billing details, and manage saved payment methods. The account's plan and
credit grants are managed by platform operations; customers should contact
support for plan changes or credit top-ups.

### Billing details

Save the billing name and supported billing address/tax fields from the Billing
page. The billing email is the account email and is displayed as read-only.

### Saved cards and important limitation

Cards can be added, selected as the default, or removed. The current UI sends
card metadata to Sayvors' stub tokenization route: brand, last four digits,
expiry, and optional cardholder name. The full card number is not sent to the
API; the UI validates it locally and the stub returns a token. Saved cards are
marked unverified until a real gateway integration is available.

**Payments are not live yet.** The current charge endpoint is a stub and moves
no money; adding a card does not charge it, create a subscription, or add
credits. The page's plan/credit display reflects the account state provided by
the API, not a completed payment.

## Notifications

Open **Dashboard → Notifications** to review the notification feed:

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
