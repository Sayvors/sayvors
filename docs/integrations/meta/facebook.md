# Meta Integration — Facebook Pages (Login for Business)

## Tenant flow

1. Tenant → Connect → backend creates OAuth transaction → returns Login
   for Business dialog URL built from the dashboard **configuration id**
   (token type + assets + permissions; no `scope` param).
2. Tenant logs in with their business portfolio, grants permissions.
3. Callback → validate state → exchange for business system-user token
   (continuous background access) → encrypt + persist connection.
4. Discover: `GET /me/accounts` → tenant selects Page(s) →
   persist Page assets (id, name, business info, granted permissions) +
   per-Page access tokens.
5. `POST /{page-id}/subscribed_apps {subscribed_fields: ["feed"]}`.

Sayvors operates on the **tenant's Page assets** — never store only the
user's Facebook id and assume it is enough.

## Capabilities → scopes (see `capabilities.py`; verify in dashboard)

- read_page: `pages_show_list`, `pages_read_engagement`, `read_insights`
- read_comments: `pages_read_user_content`
- manage_comments: `pages_manage_engagement`
- manage_page: `pages_manage_posts`, `pages_manage_metadata`
- messaging: `pages_messaging`
- manage_business_assets: `business_management`

Reference names from the Meta Permissions Reference (2026). The
`Manage a Page` guide mentions `pages_read_user_engagement`, which does not
exist in the Reference — use `pages_read_user_content`. Confirm exact
strings in App Dashboard before requesting review.

## Webhooks

`page` object: `feed` (posts/comments/reactions), `messages` (Messenger).
App-level subscription + per-Page `subscribed_apps`.

## Failure / recovery

Permission revoked or token expired → status `needs_reauth`, tenant
reconnects. Page unpublished/deleted → asset `unavailable`.
