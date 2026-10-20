# Publish Formats

A **format** is one surface a single push of media lands on. The publish
composer (`apps/web/components/dashboard/publish/`) offers one pill per
format per destination; every selected pill becomes its own publish job
(`POST /api/v1/channels/publish` → one `post.publish` job per
destination+format).

Two kinds of format exist:

| Kind | Formats | What it does |
|------|---------|--------------|
| **Feed** | `post`, `story`, `reel`, `status`, `update`, `event`, `offer` | Publishes into the network's feed or timeline |
| **Account surface** | `profile`, `banner` | Replaces the account's avatar / cover image — not a post |

## The per-platform matrix

`PLATFORM_METHODS` in `apps/web/components/dashboard/publish/types.ts` is
the single source of truth on the client; the API rejects anything else
via `_SUPPORTED_METHODS` in
`services/api/app/modules/channels/publish/router.py`; and the job handler
rejects anything the provider cannot deliver.

| Platform | Formats | Why not more |
|----------|---------|--------------|
| Facebook | post, story, reel, **profile**, **banner** | Page avatar (`POST /{page}/picture`) and cover (`POST /{page}` with `cover=<photo id>`) are both writable |
| Instagram | post, story, reel | The IG User node is read-only for the avatar — Meta's reference says "Updating: not supported". No cover concept either |
| WhatsApp | status, **profile** | The business profile photo is writable (`whatsapp_business_profile` + `profile_picture_handle`). WhatsApp has no banner |
| Google Business Profile | update, event, offer, **profile**, **banner** | The three post types are Google's own; the profile picture and cover image are location media items (`PROFILE` / `COVER` categories) |

Platforms that are wired but not enabled yet (`x`, `tiktok`, `linkedin`,
`telegram`, `snapchat`) carry a single format each. When one of them is
switched on, its account surfaces come with it — see the table at the
bottom of this document for what each API actually allows.

**Fail closed.** A format a platform cannot deliver is never offered, and
if one is requested anyway the job fails loudly with
`"<platform> does not support the <method> format"` rather than posting
something the tenant did not ask for.

## Google's three post types

`GoogleBusinessPublisher.publish_post` maps a format to a `topicType` and
adds the fields Google refuses a post without:

| Format | `topicType` | Required fields Google rejects a post without |
|--------|-------------|-----------------------------------------------|
| `update` | `STANDARD` | — |
| `event` | `EVENT` | `event.title`, `event.startDate`, `event.endDate` |
| `offer` | `OFFER` | `offer.description`, `offer.termsConditions` |

`post` is kept as a legacy alias for `STANDARD` so jobs created before
the split still publish. An unknown method raises `GoogleReviewsError`
before any request is sent.

The composer does not yet collect event dates or coupon codes, so the
publisher fills them in: a seven-day window from now for an event, and
the post's own caption and description for an offer. Collecting them from
the tenant is a follow-up, not a change to the mapping above.

## Account surfaces

`profile` and `banner` are not posts and behave differently end to end:

- **No caption.** The caption field is ignored; the format replaces an
  image on the account.
- **Nothing to delete.** The removal endpoints refuse them (409 on the
  single delete, and the batch delete closes the row with a reason that
  says the surface was left alone). The only way to change an avatar is
  to publish a new one.
- **Never swept up by "All".** The bulk "select every format" button
  covers the feed formats only. Replacing someone's identity image has
  to be a deliberate, individual choice — never a side effect of a bulk
  selection.
- **Image only.** A video cannot be an avatar or a cover, so the two
  formats are hidden when the attached media is a video.

### Per-platform delivery

- **Facebook profile picture** — `POST /{page}/picture` with
  `picture=<url>`. The parameter is `picture`, not `url`; Graph answers
  "Missing or invalid image file" (#324) for a stray `url`.
- **Facebook banner** — `POST /{page}/photos` with `published=false`,
  then `POST /{page}` with `cover=<photo id>`. The `cover` field is
  writable only as a photo id, and updating it needs the `EDIT_PROFILE`
  task and the `business_management` permission.
- **Google profile picture / cover image** — `POST /v4/{parent}/media`
  with `locationAssociation.category` set to `PROFILE` or `COVER`. A
  location has exactly one of each, and the profile picture is filed
  under a fixed resource name (`.../locations/{id}/media/profile`), so
  creating the media item replaces the old one — no delete first, which
  would leave the location with no picture if the upload failed. These
  two are the only location photos exempt from the usual "250px on the
  short edge, at least 10KB" minimum. `PROFILE` and `COVER` can only be
  set at create time — a media item's category can never be patched
  *to* one of them.
- **WhatsApp profile picture** — Meta wants the bytes, not a URL: the
  handle comes from a resumable upload session and the plain `/media`
  id is rejected as `profile_picture_handle` (#131009). The job handler
  therefore reads the image back — from our own storage when the media
  key is known, otherwise through the SSRF-guarded fetcher — and refuses
  anything that is not a JPG or PNG, or that is over Meta's 5 MB cap.

### API versions

Google's local posts are published through the **v1** Business Profile
API; location photos have no v1 resource, so they go through the
**v4.9** API (`accounts.locations.media`). Both are served from
`mybusiness.googleapis.com`, both take the same OAuth token, and both
need the `business.manage` scope this codebase already requests. v4.9's
media resource is not on Google's deprecation schedule.

## Account surfaces on the platforms that are not enabled yet

Checked against each vendor's current published spec, for whoever turns
these platforms on:

| Platform | Profile picture | Banner / cover |
|----------|-----------------|----------------|
| X (v2) | No — the v2 spec has no profile-update operation and no `users.write` scope; `profile_image_url` is response-only | No |
| LinkedIn | No — `PATCH /rest/profileImage` does not exist; `logoV2` is read-only | No — `coverPhotoV2` is read-only |
| Telegram | Yes — `setMyProfilePhoto` (Bot API 9.4, Feb 2026) and `setBusinessAccountProfilePhoto` (Bot API 9.0) | No |
| Snapchat | No — the Public Profile API exposes `logo_urls` read-only | No |

`setUserProfilePhoto` no longer exists in the Telegram Bot API; it was
replaced by `setMyProfilePhoto`.

The full per-platform research — every endpoint, scope and error code,
read from the vendors' own docs — is in
[`api-profile-banner-support.md`](./api-profile-banner-support.md).

## Crop defaults

`defaultCropFor` gives each format the shape its platform expects:

| Format | Default crop |
|--------|--------------|
| `profile` | 1:1 |
| `banner` | 16:9 |
| `story`, `reel`, `status` | 9:16 |
| everything else | the platform's post crop |

The tenant can still change the ratio in the crop modal. The preview,
the format pill thumbnail and the crop editor all render through the
same `CroppedMedia` component, so the three can never disagree about
what will be published.
