# Social Profile Picture / Banner API Endpoints (verified 2026-10-20)

All findings below were read directly from official vendor documentation on 2026-10-20.
Meta Graph API version quoted: **v26.0**. X API OpenAPI version quoted: **2.172**.
Telegram Bot API version quoted: **10.3** (latest changelog entry 2026-08-24).
LinkedIn moniker quoted: **li-lms-2026-10**. Google GBP reference "last updated 2026-09-02".

## Master table

| Platform | Profile picture? | Exact endpoint | Banner/cover? | Exact endpoint | Required scopes / permissions |
|---|---|---|---|---|---|
| Facebook Page | YES | `POST /v26.0/{page-id}/picture` | YES | `POST /v26.0/{page-id}/photos` (`published=false`) then `POST /v26.0/{page-id}` with `cover=<photo_id>` | Picture: Page token by user with `MANAGE` task + `pages_read_engagement` + `pages_show_list`. Photos upload: `CREATE_CONTENT` task + `pages_manage_posts` + `pages_read_engagement` + `pages_show_list`. Cover update: Page Admin/Editor with `EDIT_PROFILE` + `business_management` |
| Instagram | **NO** | n/a (IG User node: "Updating: This operation is not supported.") | NO | n/a | n/a (`instagram_basic` / `instagram_business_basic` are read-only) |
| Google Business Profile | **YES** (corrects common belief) | `POST https://mybusiness.googleapis.com/v4/{parent=accounts/*/locations/*}/media` with `locationAssociation.category = "PROFILE"` (or `"COVER"`) | **YES** | same endpoint with `locationAssociation.category = "COVER"` | `https://www.googleapis.com/auth/business.manage` (legacy `plus.business.manage` also accepted) |
| WhatsApp Business | YES | Resumable upload -> `POST /v26.0/{phone-number-id}/whatsapp_business_profile` with `profile_picture_handle` | **NO banner concept** | n/a | `whatsapp_business_management`; User / System User / Business Integration System User token |
| X (Twitter) v2 | **NO in current v2 spec** | `POST /2/users/me` is absent from X API v2 OpenAPI 2.172 (only `GET` on `/2/users/me`) | **NO** | n/a | No `users.write` scope exists in the v2 spec; `profile_image_url`/`profile_banner_url` are response-only fields |
| LinkedIn | **NO** | No write endpoint (`PATCH /rest/profileImage` does not exist) | **NO** | No write endpoint (`POST /rest/backgroundAsset` does not exist) | Read-only via `r_liteprofile`/`r_basicprofile`; org reads need `r_organization_admin` / `rw_organization_admin`; media upload needs `w_organization_social` / `w_member_social` / `rw_ads` |
| Telegram Bot API | **YES** (corrects belief) | `setMyProfilePhoto(photo)` (Bot API 9.4+, 2026-02-09) | NO | n/a | Bot token only |
| Snapchat | **NO** | n/a (Public Profile API is read-only for `logo_urls`) | **NO** | n/a | `snapchat-profile-api` (Public Profile API is allowlist-only) |

## 1. Facebook Page profile picture

- **Endpoint:** `POST /v26.0/{page-id}/picture` — "You can make a POST request to `picture` edge from the following paths: `/{page_id}/picture`. When posting to this edge, a ProfilePictureSource will be created."
- **Params (v26.0 reference):** `picture` (URL of the picture to upload) **or** `photo` (numeric string — "ID of the photo to use as the profile pic"); `caption`; crop params `x`, `y`, `width`, `height`, `scaled_crop_rect`; `reuse` (boolean, "Whether to reuse an existing profile pic"); `set_profile_photo_shield`; `sticker_id`. **There is no `published` param on this edge** — `published` belongs to the `photos` edge.
- **Permissions:** "The person requesting the Page access token must be able to perform the `MANAGE` task on the Page" + `pages_read_engagement` + `pages_show_list`. Error code 283 lists `pages_manage_metadata` among permissions that may be required.
- **Docs:** https://developers.facebook.com/docs/graph-api/reference/page/picture
- **Note:** `GET /{page-id}/picture?redirect=0` returns the current picture as a `ProfilePictureSource`.

## 2. Facebook Page cover photo (two-step)

**Step 1 — upload an unpublished photo**
`POST /v26.0/{page-id}/photos` with `url=<image url>` and `published=false`.
- Docs: "Upload a photo without publishing it to the `/{page-id}/photos` edge ... by adding the argument `published=false`." (add `temporary=true` for scheduled posts).
- "After you upload an unpublished photo, Facebook stores it in a temporary upload state, which means it will remain on Facebook servers for about 24 hours."
- Requirements: Page access token from a person who can perform the `CREATE_CONTENT` task + `pages_manage_posts` + `pages_read_engagement` + `pages_show_list`. Photos: .jpeg/.bmp/.png/.gif/.tiff, max 10MB.
- Response contains the photo `id`.
- Docs: https://developers.facebook.com/docs/graph-api/reference/page/photos

**Step 2 — assign it to the Page**
`POST /v26.0/{page-id}` with the param **`cover`**.
- v26.0 Page reference, Updating section: "| `cover` numeric string or integer | Update the `cover` field. This field can only be updated by the Page Admin or Page Editor with `EDIT_PROFILE` and `business_management` permissions. |"
- **Shape: a plain numeric photo id (numeric string or integer), NOT an object with `id`.** In v26.0 there is no `cover_photo` field on the Page node at all — `cover_photo` appears in v26.0 only as a *lead-gen context card* param (`cover_photo` file / `cover_photo_id` numeric string under `/{page-id}/leadgen_forms`). Guides/blogs that use `cover_photo={"id":"..."}` are based on older Graph API versions; that shape is not in the current reference.
- Optional crop/position params in the same POST: `focus_x`, `focus_y` ("Cover photo focus x/y"), `offset_x`, `offset_y` (default 50), `zoom_scale_x`, `zoom_scale_y`, `no_feed_story`, `no_notification`.
- Docs: https://developers.facebook.com/docs/graph-api/reference/page (read `cover` -> `CoverPhoto` {id, source, offset_x, offset_y})
- The `CoverPhoto` node itself is read-only: "Creating/Updating/Deleting: You can't perform this operation on this endpoint." https://developers.facebook.com/docs/graph-api/reference/cover-photo
- Permission model note: `pages_manage_metadata` = "allows your app to subscribe and receive webhooks about activity on the Page, and to **update settings on the Page**" (dependency `pages_show_list`); `pages_manage_posts` = "allows your app to create, edit and delete your Page posts" (dependencies `pages_read_engagement`, `pages_show_list`). https://developers.facebook.com/docs/permissions

## 3. Instagram — NOT SUPPORTED (confirmed)

IG User reference, "Updating" section, verbatim: **"This operation is not supported."** (and "Creating: This operation is not supported.", "Deleting: This operation is not supported.")
- `profile_picture_url` ("Your app user's Instagram profile picture URL") and `has_profile_pic` are read-only fields on the IG User node.
- Docs: https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user
- Also see the Graph API shadow node (same "Updating: not supported"): https://developers.facebook.com/docs/graph-api/reference/shadow-ig-user/
- Instagram has no banner/cover concept at all. The only Instagram "image" surfaces are feed/story/reel media publishing (`instagram_content_publish` / `instagram_business_content_publish`).

## 4. Google Business Profile — API DOES support it (correction)

- **Resource:** `accounts.locations.media` (Business Profile API v4.9) — "REST Resource: accounts.locations.media ... `MediaItem` resource represents a single media item associated with a Google My Business location".
- **Create:** `POST https://mybusiness.googleapis.com/v4/{parent=accounts/*/locations/*}/media`
  Body = `MediaItem` with `mediaFormat: "PHOTO"`, `locationAssociation: { "category": "PROFILE" | "COVER" | "EXTERIOR" | ... }` and data either `sourceUrl` (public URL) or `dataRef` (from `accounts.locations.media.startUpload`).
- **Category enum (verbatim):** "`COVER` | Cover photo. A location has only one cover photo." / "`PROFILE` | Profile photo. A location has only one profile photo." / "`LOGO` | Logo photo. `LOGO` is treated as an alias for `PROFILE`; any `LOGO` uploads are automatically mapped to `PROFILE`. Use `PROFILE` instead. This item is deprecated!"
- **"Profile and logo photo behavior" note on the create method:** "Profile photos are identified with the fixed resource name `accounts/{accountId}/locations/{locationId}/media/profile`"; `createTime` returns the Unix epoch for profile photos; `dimensions` are not populated; `sourceUrl` is replaced by a Google-hosted URL.
- **Binary upload path:** `accounts.locations.media.startUpload` -> `MediaItemDataRef` -> `POST https://mybusiness.googleapis.com/upload/v1/media/{resourceName}?uploadType=media` (Media API v1) -> then `accounts.locations.media.create` with `data.dataRef`.
- **Patch:** `PATCH https://mybusiness.googleapis.com/v4/{name=accounts/*/locations/*/media/*}` — "This can only be used to update the Category of a media item, **with the exception that the new category cannot be COVER or PROFILE**." So COVER/PROFILE can only be set at create time, never re-categorised in.
- **Scopes:** `https://www.googleapis.com/auth/business.manage` (or legacy `https://www.googleapis.com/auth/plus.business.manage`).
- **Which API surface handles location photos:** the Business Profile API `mybusiness.googleapis.com` — media lives in the **v4.9** `accounts.locations.media` resource (the v1 Business Information API has no media resource), plus the **Media API v1** (`/upload/v1/media/...`) for byte uploads.
- Docs:
  - https://developers.google.com/my-business/reference/rest/v4/accounts.locations.media
  - https://developers.google.com/my-business/reference/rest/v4/accounts.locations.media/create
  - https://developers.google.com/my-business/reference/rest/v4/accounts.locations.media/patch
  - https://developers.google.com/my-business/reference/media/rest/v1/media/upload

## 5. WhatsApp Business — profile picture yes, banner does not exist

**Step 1 — Resumable Upload API (get a file handle)**
1. `POST https://graph.facebook.com/v26.0/{APP_ID}/uploads?file_name=<NAME>&file_length=<BYTES>&file_type=image/jpeg` -> `{"id":"upload:<UPLOAD_SESSION_ID>"}`
2. `POST https://graph.facebook.com/v26.0/upload:<UPLOAD_SESSION_ID>` with header `file_offset: 0` and binary body -> `{"h":"<FILE_HANDLE>"}` ("On success, your app receives the file handle which you will use in your API calls to publish the file to your endpoint.")
   Docs: https://developers.facebook.com/docs/graph-api/guides/upload

**Step 2 — set it on the business profile**
`POST https://graph.facebook.com/v26.0/{whats-app-business-phone-number-id}/whatsapp_business_profile`
- `messaging_product` = `whatsapp` (Required)
- `profile_picture_handle` = "Profile picture media asset handle, generated via the Resumable Upload API." (string)
- Other updatable fields: `about`, `address`, `description`, `email`, `websites` (max 2), `vertical`.
- Permissions: `whatsapp_business_management`. Access tokens: User, System User, or Business Integration System User.
- Docs: https://developers.facebook.com/docs/graph-api/reference/whats-app-business-account-to-number-current-status/whatsapp_business_profile/
  and https://developers.facebook.com/documentation/business-messaging/whatsapp/reference/whatsapp-business-phone-number/whatsapp-business-profile-api
- **No banner/cover concept:** the WhatsApp Business Profile resource has exactly `messaging_product, about, address, description, email, profile_picture_url, websites, vertical`. There is no banner field anywhere in the API.

## 6. X (Twitter) v2 — no profile-update endpoint in the current v2 spec

- The published X API v2 OpenAPI (https://docs.x.com/openapi.json, `info.version: 2.172`) defines `/2/users/me` with a **`get` operation only**. There is no `post`/`put` for `/2/users/me` and no `users.write` scope anywhere in the spec (verified by grep over the full spec).
- `profile_image_url` ("The URL to the profile image for this User") and `profile_banner_url` ("The URL to the profile banner for this User") appear **only as response properties** of the `User` schema and in the `user.fields` enum — they are not request parameters.
- The v2 docs index (https://docs.x.com/x-api/llms.txt) contains **no "update profile" page** under Users.
- Therefore `POST /2/users/me` with `profile_image_url` (and the `write.users`/`users.write` scope) is **not part of the currently published v2 API**. It was documented in earlier Twitter API v2 docs (https://developer.twitter.com/en/docs/twitter-api/users/update-profile-information, now redirects into docs.x.com); treat it as unverified/legacy.
- **Banner/header:** no endpoint. v1.1's `account/update_profile_banner` and `account/update_profile_image` are gone with Standard v1.1 access (turned off 2023-04-29; only media-upload endpoints remained).
- Docs: https://docs.x.com/x-api/users/get-my-user.md , https://docs.x.com/openapi.json , https://docs.x.com/x-api/llms.txt , https://docs.x.com/x-api/migrate/x-api-endpoint-map

## 7. LinkedIn — no write endpoints for logo, profile picture, or banner

- **Member profile picture:** the Profile API is read-only. `GET https://api.linkedin.com/v2/me` (or `/v2/people/(id:{id})`) returns `profilePicture.displayImage` as `urn:li:digitalmediaAsset:...`. Docs: https://learn.microsoft.com/en-us/linkedin/shared/integrations/people/profile-api
  Permissions there are `r_liteprofile` / `r_basicprofile` / `r_compliance` (note: `r_basicprofile` "grants only a subset of fields provided in v1"). The old `r_litew_member` name is the pre-2023 v2 scope name.
- **Company Page logo & cover:** exposed as **read-only** Organization fields — `logoV2` ("The entity's logo") and `coverPhotoV2` ("The entity's background cover image", Admin-Only). `GET https://api.linkedin.com/rest/organizations/{organizationId}` / `GET /rest/organizationsLookup?...`. No `PATCH /rest/organizations/{id}` with logo/cover is documented.
  Docs: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/organizations/organization-lookup-api
- **There is no `PATCH /rest/profileImage` and no `POST /rest/backgroundAsset`.** (Grepped every current LinkedIn doc page in the Community Management TOC — zero hits.)
- **What *does* exist** (but is for content, not branding):
  - Images API: `POST https://api.linkedin.com/rest/images?action=initializeUpload` -> PUT bytes to `uploadUrl` -> `urn:li:image:...`. Requires `rw_ads`, `w_member_social`, `w_organization_social`, `w_power_creators`. Docs: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/images-api
  - Legacy Assets API: `POST https://api.linkedin.com/rest/assets?action=registerUpload` -> PUT -> `urn:li:digitalmediaAsset:...` ("The Images API replaces the Assets API"). Requires `w_compliance`, `w_organization_social`, `w_member_social`, `rw_ads`. Docs: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/vector-asset-api
- **Org scopes:** `rw_organization_admin` ("Manage organizations pages and retrieve reporting data") / `r_organization_admin`; the caller must also hold the org role type `ADMINISTRATOR`. Docs: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/organizations/organization-access-control-by-role

## 8. Telegram Bot API — bots CAN set their own photo (correction)

- **`setMyProfilePhoto`** — "Changes the profile photo of the bot. Returns *True* on success." Param: `photo` (`InputProfilePhoto`, required) = `InputProfilePhotoStatic` or `InputProfilePhotoAnimated`.
  https://core.telegram.org/bots/api#setmyprofilephoto (markdown source: https://core.telegram.org/bots/api/methods/setmyprofilephoto.md)
- **`removeMyProfilePhoto`** — "Removes the profile photo of the bot."
- **Added in Bot API 9.4, February 9, 2026** — changelog verbatim: "Added the methods `setMyProfilePhoto` and `removeMyProfilePhoto`, allowing bots to manage their profile picture." https://core.telegram.org/bots/api-changelog
- **Managed business accounts** (Bot API 9.0, April 11, 2025): "Added the class `InputProfilePhoto` ... Added the methods `setBusinessAccountProfilePhoto` and `removeBusinessAccountProfilePhoto`, allowing bots to change the profile photo of a managed business account."
- **`setUserProfilePhoto` no longer exists** in the current Bot API: it is absent from the method list in https://core.telegram.org/bots/api and https://core.telegram.org/bots/api/methods/setuserprofilephoto.md returns 404 (checked 2026-10-20). It existed in older Bot API versions (it set a *user's* photo in a chat, requiring bot admin). Do not design against it.
- `setChatPhoto` is a different thing: it sets the photo of a **group/supergroup/channel** avatar.
- No banner/cover concept in Telegram.
- Auth: the bot's own token only. No OAuth scopes.

## 9. Snapchat — no profile picture / banner API

- Public Profile API is read-only for profile branding. `GET https://businessapi.snapchat.com/public/v1/public_profiles/{profile_id}` returns `logo_urls` (`original_logo_url`, `discover_feed_logo_url`, `mega_profile_logo_url`, `manage_profile_logo_url`) as **read-only** values.
- "Profile Asset Management" only covers media/stories/spotlights/saved stories (`POST /v1/public_profiles/{profile_id}/media`, `.../stories`, `.../spotlights`, `.../saved_stories`) — content, not avatar/banner.
- Public Profile API is **allowlist-only**; OAuth scope `snapchat-profile-api`; access token must come from an Ads Manager Business Account OAuth app (not the Developer Portal).
- Business Public Profile setup (including the logo/avatar) is done in Ads Manager / Business Dashboard.
- Docs: https://developers.snap.com/marketing-api/Public-Profile-API/GetStarted , https://developers.snap.com/marketing-api/Public-Profile-API/ProfileAssetManagement , https://businesshelp.snapchat.com/s/article/public-profiles-business

## NOT SUPPORTED (summary + reason)

1. **Instagram** — IG User node write operations are explicitly "not supported" in Meta's own reference; `profile_picture_url` is read-only. No cover/banner concept.
2. **X (Twitter) v2** — the current published v2 OpenAPI (2.172) has only `GET /2/users/me`; there is no profile-update operation and no `users.write` scope; `profile_image_url` / `profile_banner_url` are response-only.
3. **LinkedIn** — logo (`logoV2`) and cover (`coverPhotoV2`) are read-only fields on the Organization resource; member `profilePicture` is read-only; the Images/Assets APIs only create post & ad media. No `profileImage` or `backgroundAsset` resource exists.
4. **Snapchat** — Public Profile API exposes `logo_urls` read-only; avatar/banner must be set in Ads Manager.
5. **WhatsApp Business (banner only)** — the business profile resource has no banner/cover field.
6. **Telegram (banner only)** — no banner/cover concept.

## Corrections to the assumptions in the request

| Assumption | Verdict |
|---|---|
| Instagram cannot update profile picture | **Correct** |
| GBP photos must be changed in the UI, no API | **Incorrect** — `accounts.locations.media.create` with `category: PROFILE` / `COVER` is supported |
| Telegram bots cannot set their own profile photo | **Incorrect as of 2026-02-09** — `setMyProfilePhoto` (Bot API 9.4) |
| FB cover = `POST /{page-id}` with `cover_photo` = object with `id` | **Incorrect for v26.0** — the param is `cover` = plain numeric photo id; `cover_photo` is not a Page field in v26.0 |
| FB picture endpoint takes `published` | **Incorrect** — `published` is on the `photos` edge, not the `picture` edge |
| X: `POST /2/users/me` with `profile_image_url`, scope `write.users` | **Not in the current v2 spec** (GET only, no `users.write`) |
| LinkedIn: `PATCH /rest/profileImage`, `POST /rest/backgroundAsset` | **Do not exist** in current docs |
| Snapchat: no avatar/banner API | **Correct** |

## Sources

| # | Title | URL |
|---|---|---|
| 1 | Graph API v26.0 — Page Picture | https://developers.facebook.com/docs/graph-api/reference/page/picture |
| 2 | Graph API v26.0 — Page Photos | https://developers.facebook.com/docs/graph-api/reference/page/photos |
| 3 | Graph API v26.0 — Page (Updating section, `cover`) | https://developers.facebook.com/docs/graph-api/reference/page |
| 4 | Graph API v26.0 — Cover Photo | https://developers.facebook.com/docs/graph-api/reference/cover-photo |
| 5 | Meta Permissions Reference | https://developers.facebook.com/docs/permissions |
| 6 | Instagram Platform — IG User reference | https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user |
| 7 | Graph API — Resumable Upload (file handles) | https://developers.facebook.com/docs/graph-api/guides/upload |
| 8 | Graph API — WhatsApp Business Profile | https://developers.facebook.com/docs/graph-api/reference/whats-app-business-account-to-number-current-status/whatsapp_business_profile/ |
| 9 | WhatsApp Business Profile API (reference) | https://developers.facebook.com/documentation/business-messaging/whatsapp/reference/whatsapp-business-phone-number/whatsapp-business-profile-api |
| 10 | GBP — accounts.locations.media | https://developers.google.com/my-business/reference/rest/v4/accounts.locations.media |
| 11 | GBP — accounts.locations.media.create | https://developers.google.com/my-business/reference/rest/v4/accounts.locations.media/create |
| 12 | GBP — accounts.locations.media.patch | https://developers.google.com/my-business/reference/rest/v4/accounts.locations.media/patch |
| 13 | GBP — Media API v1 upload | https://developers.google.com/my-business/reference/media/rest/v1/media/upload |
| 14 | X API v2 — Get Users Me (OpenAPI 2.172) | https://docs.x.com/x-api/users/get-my-user.md |
| 15 | X API v2 — full OpenAPI spec | https://docs.x.com/openapi.json |
| 16 | X API v2 — docs index | https://docs.x.com/x-api/llms.txt |
| 17 | LinkedIn — Organization Lookup (logoV2 / coverPhotoV2) | https://learn.microsoft.com/en-us/linkedin/marketing/community-management/organizations/organization-lookup-api |
| 18 | LinkedIn — Organization Access Control by Role | https://learn.microsoft.com/en-us/linkedin/marketing/community-management/organizations/organization-access-control-by-role |
| 19 | LinkedIn — Images API | https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/images-api |
| 20 | LinkedIn — Assets API (legacy) | https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/vector-asset-api |
| 21 | LinkedIn — Member Profile API | https://learn.microsoft.com/en-us/linkedin/shared/integrations/people/profile-api |
| 22 | Telegram Bot API — setMyProfilePhoto | https://core.telegram.org/bots/api#setmyprofilephoto |
| 23 | Telegram Bot API changelog | https://core.telegram.org/bots/api-changelog |
| 24 | Snap — Public Profile API Get Started | https://developers.snap.com/marketing-api/Public-Profile-API/GetStarted |
| 25 | Snap — Profile Asset Management | https://developers.snap.com/marketing-api/Public-Profile-API/ProfileAssetManagement |

## Confidence notes

- **High confidence:** FB (picture/photos/cover params, scopes), Instagram ("not supported" quote), WhatsApp (handle flow + scope + no banner), Telegram (`setMyProfilePhoto` + changelog date), Google GBP (media resource, categories, scopes), LinkedIn (absence of write endpoints, read-only logo/cover), Snapchat (read-only logo_urls).
- **Medium confidence:** X. The current published spec unambiguously lacks a profile-update operation, but X has removed endpoints from docs without deprecating them server-side. If a product depends on this, verify with a live `POST /2/users/me` against api.x.com before shipping.
- **Medium confidence:** the exact permission Meta enforces at runtime for `POST /{page-id}/picture`. The v26.0 reference states task + `pages_read_engagement` + `pages_show_list`; error 283 also names `pages_manage_metadata` and `pages_manage_posts`. In practice Meta's runtime is stricter than the doc, so request `pages_manage_posts` + `pages_manage_metadata` for cover/picture flows.

## Open questions

1. Does `POST /{page-id}` still accept `cover_photo={"id": "<photo_id>"}` as a legacy alias in v26.0, or was it removed? The v26.0 reference only documents `cover`. Unverified (no official statement).
2. Whether Google GBP API-uploaded COVER/PROFILE photos require re-moderation, and whether the API path enforces the same crop/size rules as the GBP UI (the reference says PROFILE/COVER are exempt from the 250px-short-edge minimum).
3. Whether the LinkedIn partner program exposes any private (undocumented) Page-branding write endpoint.
