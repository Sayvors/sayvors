# Google Business Profile Cover Photo Research

**Research date:** 2026-11-17
**Scope:** Official Google sources only (support.google.com/business, developers.google.com/my-business, developers.google.com/maps, blog.google). No SEO blogs used.
**Labels:** CONFIRMED = explicit in an official source; NOT STATED = official docs silent; AMBIGUOUS = sources conflict, wording is soft, or attribution unverified.

## Executive Summary

Google officially exposes a merchant-set cover photo (web: "Add a cover photo" / "Change cover"; app: "Cover photo or Logo") and a logo (API category PROFILE), but Google Help explicitly warns that setting a cover photo does not guarantee it will be the first image. Help also states that if the chosen cover is low-quality or other sources suggest a better image, a user-submitted photo may be selected instead, and that on the profile newest media appears first. There is no documented official method to drag/drop-reorder gallery photos, to promote an arbitrary existing gallery photo to first, or to change a cover via API after creation (UpdateMediaItem explicitly cannot set COVER or PROFILE). No official source found defines the exact ranking algorithm.

## Key Findings

### 1. Official terminology and taxonomy

1.1 Help Center three-way taxonomy (logo / cover / business photos). CONFIRMED.
Source: Manage your Business Profile photos and videos, https://support.google.com/business/answer/6103862?hl=en (no date shown).
Quote: "Logo: Help your customers recognize your business on Google. For businesses that have their basic information, such as a phone number or hours of operation, the Business Profile highlights the logo. Cover photo: Set a cover photo at the top of your profile that best represents your business. In some instances, this action doesn't guarantee the cover photo will show up as the first image for your business. Business photos: Add different photos to highlight features of your business to attract and inform customers."
Repeated verbatim in Complete your Business Profile on Google, https://support.google.com/business/answer/10515606?hl=en (no date shown).

1.2 API category taxonomy. CONFIRMED.
Source: REST Resource accounts.locations.media Category, https://developers.google.com/my-business/reference/rest/v4/accounts.locations.media (current API v4.9; no page date).
Quote: COVER - "Cover photo. A location has only one cover photo." PROFILE - "Profile photo. A location has only one profile photo." LOGO - "Logo photo. LOGO is treated as an alias for PROFILE; any LOGO uploads are automatically mapped to PROFILE. Use PROFILE instead." (deprecated). Other enums: EXTERIOR, INTERIOR, PRODUCT, AT_WORK, FOOD_AND_DRINK, MENU, COMMON_AREA, ROOMS, TEAMS, ADDITIONAL.
Also in RPC reference google.mybusiness.v4, https://developers.google.com/my-business/reference/rpc/google.mybusiness.v4 (no date).

1.3 "Avatar" is not official GBP terminology. NOT STATED.
The word avatar does not appear in the official GBP Help or GBP API docs retrieved. Nearest official concepts: Help Center "Logo" and API PROFILE / deprecated LOGO. (Changelog "Reviewer Profile Photo" refers to reviewer avatars in reviews, not the business photo - Change Log v4.2, https://developers.google.com/my-business/content/change-log.)

1.4 Business-specific photo categories. CONFIRMED.
Source: Tips for business-specific photos on your Business Profile, https://support.google.com/business/answer/6123536?hl=en (no date shown).
Categories: Exterior, Interior, Product, Photos at work, Food & drink, Common areas, Rooms, Team photos. Google recommendation, quote: "Add at least three great exterior photos to help customers recognize your business." / "Add at least three great interior photos to show customers what your business feels like inside."

1.5 Terminology mismatch between UI and API. CONFIRMED.
Help/UI says "Logo"; API says PROFILE and treats LOGO as deprecated alias mapped to PROFILE. Bulk upload spreadsheet uses columns "Logo," "Cover," "Other Photos" (https://support.google.com/business/answer/3370250?hl=en).

### 2. What determines the FIRST / cover image; merchant control

2.1 Setting a cover photo is a preference, not a guarantee of display position. CONFIRMED.
Sources (identical sentence on all): Manage your Business Profile photos and videos (Computer, Android and iOS variants), https://support.google.com/business/answer/6103862?hl=en ; Complete your Business Profile on Google, https://support.google.com/business/answer/10515606?hl=en .
Quote: "Cover photo: Set a cover photo at the top of your profile that best represents your business. In some instances, this action doesn't guarantee the cover photo will show up as the first image for your business."

2.2 Google may substitute a user-submitted photo. CONFIRMED.
Source: 6103862, section "Logo photo missing".
Quote: "If the cover photo you select is low-quality or if other sources suggest that it's not the best photo to represent your business, a user-submitted photo may be selected instead."

2.3 Newest-uploaded-first is the stated gallery default. CONFIRMED.
Source: 6103862, tip. Quote: "You can find your uploaded photos and videos on your Business Profile, where your newest media appears first."

2.4 Google own blog frames it as a "preferred" photo. CONFIRMED (dated source).
Source: "Helping businesses capture their identity with Google My Business", https://blog.google/products-and-platforms/products/maps/helping-businesses-capture-their-identity-google-my-business , 2019-06-20, Amir Fish, Group Product Manager, Google My Business.
Quote: "Show personality with cover photos: Businesses can easily set their preferred profile cover photo, putting their best foot forward." Also: "Identify companies with more prominent logos: Businesses have an additional branding opportunity with the logo feature. Those that have completed their core information (phone number, hours, etc) will have their logo displayed at the top right-hand side of their profile."

2.5 There IS a manual cover-photo control. CONFIRMED. "Add a cover photo" / "Change cover" (web) and "Cover photo or Logo" (app) are documented - see section 3. However the exact label "Set as cover photo" applied to an existing gallery item does NOT appear in any official Help/API page retrieved; it appears only in Help Community posts whose official status I could not verify (threads are JS-rendered and returned no content). AMBIGUOUS - community phrasing only.

2.6 "Preferred Photo" was a historical API concept. CONFIRMED (historic) / NOT STATED (current implementation).
Source: API Change Log, https://developers.google.com/my-business/content/change-log , section v3 (no date attached to this entry).
Quote: "Preferred Photo: Indicate which photo you'd prefer to show up first in Google Maps and Search."
No corresponding preferred field, flag or method exists in the current v4 MediaItem resource or v4 RPC reference. Bulk upload doc explicitly lists "Preferred photo" and "Profile photo" under "Unsupported fields" (https://support.google.com/business/answer/3370250?hl=en). NOT STATED whether a preferred-photo flag still exists internally.

2.7 The exact algorithm selecting the displayed first image is not published. NOT STATED.
No official source retrieved defines ranking criteria beyond (a) the "doesn't guarantee" warning, (b) the "low-quality / other sources" clause, and (c) "newest media appears first." Claims such as "re-uploading makes it first" are not officially documented.

### 3. Exact official steps and constraints

3.1 Web (Google Search / Maps, computer). CONFIRMED.
Sources: https://support.google.com/business/answer/6103862?hl=en and "2. Add your logo & cover photo", https://support.google.com/business/answer/16335217?hl=en (no dates shown).
Quote: "On your computer, open Google Search or Maps. Search for your business's name and city. To add a cover photo or logo, click Photos then Add a cover photo or Add a logo. To change the cover photo or logo, click Change cover or Change logo. Select your photo."
Guide variant: "Go to your Business Profile. Select Photos then Add a cover photo or Add a logo. To change the cover photo or logo, select Change cover or Change logo. Select Select image. Select the photo you want to upload. Select Open."

3.2 Android. CONFIRMED. Source: 6103862 Android variant (co=GENIE.Platform%3DAndroid).
Quote: "On your Android device, open the Google Maps app. At the bottom right, tap Business. To add a cover photo or logo, tap More then Cover photo or Logo. Select your photo. At the top right, tap Post." / "Tip: If you already have a cover photo or logo, you can update it."

3.3 iOS. CONFIRMED. Source: 6103862 iPhone/iPad variant (co=GENIE.Platform%3DiOS).
Quote: "On your iPhone or iPad, open the Google Maps app. At the bottom right, tap Business. To add a cover photo or logo, tap More then Cover photo or Logo. Select your photo. At the bottom right, tap Publish." / "Tip: If you already have a cover photo or logo, you can update it."

3.4 Preconditions. CONFIRMED. Source: "1. Add photos & videos", https://support.google.com/business/answer/16334511?hl=en .
Quote: "You must be signed in to the Google Account associated with your Business Profile. Your Business Profile must be verified." Also from 6103862: "Important: Your photos and videos show up on Google only after you verify your Business Profile."

3.5 Photo file constraints. CONFIRMED. Sources: 6103862 and 6123536.
Quote: "Format: JPG or PNG. Size: Between 10 KB and 5 MB. Recommended resolution: 720 px tall, 720 px wide. Minimum resolution: 250 px tall, 250 px wide. Quality: The photo should be in focus and well lit, and have no significant alterations or excessive use of filters [or AI]. In other words, the image should represent reality."
Video: "Duration: Up to 30 seconds long; File size: Up to 75 MB; Resolution: 720p or higher."

3.6 Aspect ratio. NOT STATED. No official GBP help/API page retrieved specifies a required aspect ratio for cover or profile photos; docs give pixel dimensions, not a ratio. ("restricted to its original aspect ratio" appears only in unrelated Places API resizing docs.)

3.7 API constraints. CONFIRMED. Sources: https://developers.google.com/my-business/reference/rest/v4/accounts.locations.media and .../media.customers .
Quote: "With the exception of PROFILE and COVER category, all photos must measure a minimum of 250px on the short edge, with a file size of at least 10240 bytes." Also: description "cannot be modified ... but can be set when creating a new media item that is not a cover photo."
Max item count, RPC ListMediaItemsRequest: "The default value is 100, which is also the maximum supported number of media items able to be added to a location with the My Business API. Maximum page size is 2500."
Singular covers: "A location has only one cover photo"; "A location has only one profile photo" (Category enum).

3.8 Moderation / visibility. CONFIRMED. Source 6103862.
Quote: "Pending: The media is in either the upload or processing stage, or your profile is currently not verified. Pending media doesn't show up on Google Search or Maps to customers." / "Not approved: The media is flagged and has violated policies. Since it was flagged, the media doesn't show up on Google Search or Maps." / "Live: The media shows up on Search and Maps for customers." / "It can take up to 24-48 hours before your photos and videos show on your Business Profile."
Duplicate warning (16335217): "To prevent your photos from being marked as duplicates, only upload each photo once. You can upload as a logo, cover photo, or a general photo."

3.9 Permissions. CONFIRMED (with caveat). Source: Manage your Business Profile owners & managers, https://support.google.com/business/answer/3403100?hl=en (no date shown).
Quote: "Managers, formerly known as site managers, have mostly the same access to the profile as owners. The only exception is they can't add or remove users or remove the profile."
Capability table lists "Add, delete, and edit cover photos and additional photos" and "Add, delete, and edit logos" - caveat: checkmark icons did not render in text extraction, so exact per-role marks could not be visually verified; the quoted sentence supports manager capability by direct implication. API OAuth scopes: https://www.googleapis.com/auth/business.manage or https://www.googleapis.com/auth/plus.business.manage (media.patch doc).

3.10 Bulk upload. CONFIRMED. Source: https://support.google.com/business/answer/3370250?hl=en (no date shown).
Quote: "Choose a photo for the Logo, Cover, or Other Photos category. In that category's column, add the photo URL. If you add multiple photos in the Other Photos column, separate the URLs with commas." / "Unsupported fields ... Preferred photo, Profile photo."
Also: "Photos are optional. Your profile might show photos of your business on Maps and Search, even if you don't add them ... Your business photos on Google may come from you or other sources." Bulk upload applies to businesses with 10+ locations (6103862).

### 4. Gallery ordering / drag-and-drop / re-uploading

4.1 Stated ordering rule: newest media first. CONFIRMED. (Quote in 2.3.)

4.2 No documented drag-and-drop or reorder control. NOT STATED.
No official Help Center, GBP API or blog page retrieved describes reordering gallery photos by drag/drop or by any manual ordering control. The only "drag" reference found in Google Business Profile Help is for the menu editor (About the menu editor, https://support.google.com/business/answer/9455840?hl=en-gb: "You have the option to drag..."), which is unrelated to the photo gallery.

4.3 No official statement that re-uploading changes the first/gallery position. NOT STATED.
Official docs say only that uploading a cover is a preference, that newest appears first, and that duplicate photos may be flagged. Help Community threads ask about reordering (e.g. https://support.google.com/business/thread/335521097/can-i-reorder-the-photos-on-my-business-page-so-a-different-one-shows-up-first?hl=en and https://support.google.com/business/thread/170019114/i-want-to-keep-my-newly-uploaded-photos-to-show-first?hl=en ), but their replies were not retrievable because the community UI is JavaScript-rendered; therefore I cannot verify whether any reply is an officially marked Google/Product Expert answer. Any such claim is AMBIGUOUS / unverified.

### 5. API: documented method to set/reorder first or cover photo

5.1 Setting a cover at creation. CONFIRMED.
Source: Upload media, https://developers.google.com/my-business/content/upload-photos (no date shown).
Request: POST https://mybusiness.googleapis.com/v4/accounts/{accountId}/locations/{locationId}/media with body { "mediaFormat": "PHOTO", "locationAssociation": { "category": "COVER" }, "sourceUrl": "http://example.com/biz/image.jpg" }. Same pattern for upload-from-bytes with "category": "COVER". PROFILE is the corresponding category for the logo/profile photo.

5.2 Changing to COVER/PROFILE after creation. CONFIRMED IMPOSSIBLE via documented API.
Source: Method accounts.locations.media.patch, https://developers.google.com/my-business/reference/rest/v4/accounts.locations.media/patch , and RPC UpdateMediaItem.
Quote: "Updates metadata of the specified media item. This can only be used to update the Category of a media item, with the exception that the new category cannot be COVER or PROFILE."

5.3 No reorder / set-first / set-preferred method exists. CONFIRMED (by exhaustive method list).
Source: REST methods summary https://developers.google.com/my-business/reference/rest/v4/accounts.locations.media and RPC Media service. Complete method set: media.create, media.delete, media.get, media.list, media.patch, media.startUpload (plus media.customers.get / media.customers.list for user-contributed media, which are read-only). No reorder, set-first or set-preferred endpoint documented. MediaItem has no order/index/preferred field.

5.4 Food-menu "preferred photo" is a different, narrow concept. CONFIRMED (must not be generalized).
Source: RPC google.mybusiness.v4 FoodMenuItemAttributes, and https://developers.google.com/my-business/reference/rest/v4/FoodMenus .
Quote: "media_keys[] ... Only photo media is supported. When there are multiple photos associated, the first photo is considered as the preferred photo." Applies ONLY to photos on a food-menu dish, not to the location gallery or cover.

5.5 Maps Platform / Places API is read-only and offers no cover control. CONFIRMED.
Source: Place Photos (New), https://developers.google.com/maps/documentation/places/web-service/place-photos .
Quote: "The Place Photos (New) service is a read-only API that lets you add high quality photographic content to your application." / "Each API can return up to 10 photos for a place location." / "Photos returned by Place Photos (New) are sourced from a variety of locations, including business owners and user contributed photos."
No documented concept of cover, first, or merchant-controlled ordering. (Maps JavaScript sample's place.photos[0] "Display the first photo" is a display example, not an ordering guarantee - https://developers.google.com/maps/documentation/javascript/examples/place-photos.)

## Conflicting Information / Tensions in Official Sources

1. "Set a cover photo at the top of your profile" vs "doesn't guarantee the cover photo will show up as the first image" - both in the same Help sentence. Best reading: merchant expresses a preference; Google renderer decides what actually displays first. Explicitly qualified guarantee, not a hard contradiction.
2. API "A location has only one cover photo" (singular, deterministic) vs Help "a user-submitted photo may be selected instead" - can coexist: one stored merchant-designated cover, but the image served to users may be another photo.
3. 2019 blog "preferred profile cover photo" vs current Help "doesn't guarantee first" - consistent if "preferred" is read literally; blog does not claim a guarantee.
4. v3 changelog "Preferred Photo: Indicate which photo you'd prefer to show up first" vs current v4 docs with no such field and bulk upload listing "Preferred photo" as unsupported - appears to be a removed/legacy capability; no official doc explicitly announces its removal. AMBIGUOUS (historical feature status).
5. Help/UI "Logo" vs API PROFILE (with LOGO deprecated) - documented alias, but terminology inconsistent across surfaces.

## Confidence Notes

High confidence: taxonomy, manual cover/logo controls and exact steps, file constraints, moderation states, API method set and the COVER/PROFILE patch restriction, read-only Places API - all explicit in primary official docs.
Medium confidence: role permission inference ("Managers have mostly the same access ... only exception ..." - checkmarks not extractable); "newest first" is stated but reads as UI observation rather than published ranking algorithm.
Low confidence / unverified: Help Community reply attribution and phrases "Set as Cover Photo" / "choosing a cover does not guarantee that it will always be displayed first" / "This is not a feature that is currently available to order the..." - appeared in search snippets or thread titles, but thread bodies could not be fetched (JS-rendered). Do NOT treat them as official Google statements.
Dating: no publication/update dates displayed on the Google Help Center articles or API reference pages retrieved; assume "as of retrieval 2026-11-17". Only dated sources are the blog post (2019-06-20) and dated 2026 changelog entries (unrelated to photos).

## Open Questions

1. Does Google still maintain an internal "preferred photo" signal (v3) distinct from the COVER category, and if so is it settable anywhere today? Official docs silent.
2. What is the exact weighting (quality signals, user-contributed photos, recency, search context) used to pick the rendered first photo? Not published.
3. Is there any UI path to promote an arbitrary existing gallery (business) photo to cover without re-uploading? Official docs only document "Add a cover photo" and "Change cover"; no "set as cover" from gallery is documented.
4. Whether Help Community replies in cited threads are officially marked (Google/Product Expert) - unresolved due to JS rendering.

## Sources

1. Manage your Business Profile photos & videos (Computer / Android / iOS) - https://support.google.com/business/answer/6103862?hl=en - no date - Primary: cover warning, steps, constraints, moderation, newest-first, user-submitted fallback.
2. Complete your Business Profile on Google - https://support.google.com/business/answer/10515606?hl=en - no date - Taxonomy + cover warning.
3. 2. Add your logo & cover photo - https://support.google.com/business/answer/16335217?hl=en - no date - Exact web steps + duplicate warning.
4. 1. Add photos & videos - https://support.google.com/business/answer/16334511?hl=en - no date - Sign-in + verification preconditions.
5. Tips for business-specific photos - https://support.google.com/business/answer/6123536?hl=en - no date - Photo taxonomy, min counts, file constraints.
6. Business Profile photos, videos & posts content policy - https://support.google.com/business/answer/7213077?hl=en - no date - Moderation policy anchor.
7. Manage your Business Profile owners & managers - https://support.google.com/business/answer/3403100?hl=en - no date - Permission roles.
8. Create a bulk upload spreadsheet - https://support.google.com/business/answer/3370250?hl=en - no date - Bulk Cover/Logo; "Preferred photo" unsupported.
9. Helping businesses capture their identity with Google My Business - https://blog.google/products-and-platforms/products/maps/helping-businesses-capture-their-identity-google-my-business - 2019-06-20 - "preferred profile cover photo"; logo placement.
10. API Change Log - https://developers.google.com/my-business/content/change-log - v4.9 entries 2026-10-09 etc.; v3 entry undated - Historical "Preferred Photo".
11. REST Resource accounts.locations.media - https://developers.google.com/my-business/reference/rest/v4/accounts.locations.media - no date - Category enum, size rules.
12. REST Resource media.customers - https://developers.google.com/my-business/reference/rest/v4/accounts.locations.media.customers - no date - Customer media read-only; size rule.
13. Method accounts.locations.media.patch - https://developers.google.com/my-business/reference/rest/v4/accounts.locations.media/patch - no date - Cannot patch to COVER/PROFILE.
14. Upload media - https://developers.google.com/my-business/content/upload-photos - no date - Set COVER at creation.
15. API FAQ - https://developers.google.com/my-business/content/faq - no date - Media API scope summary.
16. RPC reference google.mybusiness.v4 - https://developers.google.com/my-business/reference/rpc/google.mybusiness.v4 - no date - Full Media method set; max 100 items; food-menu "preferred photo".
17. Place Photos (New) - https://developers.google.com/maps/documentation/places/web-service/place-photos - EEA ToS note 2025-07-08 - Read-only; up to 10 photos; no cover control.
18. Place Photos sample (Maps JavaScript) - https://developers.google.com/maps/documentation/javascript/examples/place-photos - no date - "Display the first photo" is a sample, not a guarantee.
Unverified Help Community threads (snippets only, JS-rendered bodies): https://support.google.com/business/thread/452569038 ; /335521097 ; /170019114 ; /334037033 ; /226828455 - not citable as official.
