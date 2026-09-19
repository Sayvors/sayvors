# Meta Integration — Instagram (Business/Professional, via Page)

One stack only: **Instagram API with Facebook Login** (via Messenger
Platform, `graph.facebook.com`). The `graph.instagram.com` (Instagram Login)
stack is deliberately not built — revisit only if product needs it.

## Relationship (modelled explicitly)

```
Meta Business Portfolio → Facebook Page → Instagram Business/Professional account
```

`meta_assets.parent_asset_id` links the IG asset to its Page.

## Tenant flow

1. Tenant connects Facebook (Login for Business) first.
2. Discover: `GET /{page-id}?fields=instagram_business_account` per Page →
   persist IG asset (IG id, username, `parent_asset_id` = Page).
3. **Eligibility check at connect** (fail with actionable message):
   - Professional account (Business/Creator), not personal.
   - Public account (required for comment webhooks).
   - Page admin granted MODERATE (comments) / MESSAGE (messaging) tasks.
   - `IG Settings → Messages and story replies → Message controls →
     Connected Tools → Allow Access to Messages` enabled (operator step —
     shown in UI copy).

## Capabilities → scopes (verify in dashboard)

`instagram_basic`, `instagram_manage_messages`, `instagram_manage_comments`,
`instagram_content_publish` (a `..._publishing` variant also appears in Meta
docs — confirm exact string in App Dashboard), `instagram_manage_insights`,
plus Page-side `pages_show_list`, `pages_read_engagement`,
`pages_manage_metadata`. Old `business_*` scopes were deprecated Jan 2025.

## Webhooks

`instagram` object: `comments`, `messages`, … Business verification required
for webhooks; Advanced access required for non-owned accounts.

## Failure / recovery

IG unlinked from Page, switched to personal/private, or messaging access
revoked → asset `unavailable` / connection `needs_reauth`; tenant
reconnects and re-selects.
