# Google Business Profile API v4 — localPosts Field Requirements & Validation
Research date: 2026-11-16.

## Executive Summary
Official docs mark only topicType as literally "Required" at top level, but also state event is "Required for topic types EVENT and OFFER." Nearly every other validation developers hit (1500-char summary, 58-char title, full four-field schedule, single-photo, CALL-url rules) is NOT in current published docs and comes from community probing. The "Manage local posts" guide's OFFER example uses topicType OFFER with a callToAction and NO event — contradicting the resource reference. No "InvalidEventTime" error exists in GBP (that is Microsoft Ads CAPI).

## Q1 — REQUIRED vs OPTIONAL
| Field | Official | Observed |
|---|---|---|
| topicType | REQUIRED | REQUIRED |
| event | Required for EVENT & OFFER | confirmed |
| summary | Optional | STANDARD needs summary OR media |
| media[] | Optional | max ~1 photo |
| callToAction | Optional; "Ignored for OFFER" | invalid on OFFER |
| offer | Optional; only when OFFER | all sub-fields Optional |
| languageCode | Optional | optional |
| scheduledTime | Optional | optional |
STANDARD: summary and/or media at least one. EVENT: event{title + schedule}. OFFER: event block per docs + offer object.

## Q2 — EVENT
- event.title: required (community), max 58 chars, error "Must be at most 58 characters".
- event.schedule (TimeInterval): "must contain all fields to be valid" -> startDate, startTime, endDate, endTime all required.
- startDate/endDate = {year 1-9999|0, month 1-12|0, day 1-31 valid|0}.
- startTime/endTime = {hours 0-23 (maybe 24), minutes 0-59, seconds 0-59 (maybe 60), nanos 0-999999999}.
- NO timezone field. Cross-field validations (end before start, past dates, max duration) not documented. Generic ErrorCode: INVERTED_RANGE, VALUE_OUTSIDE_ALLOWED_RANGE, EXPIRED_VALUE, MISSING_DEPENDENT_FIELD.

## Q3 — OFFER
- couponCode, redeemOnlineUrl, termsConditions: all explicitly Optional. No official "at least one" rule.
- event block: docs say required for OFFER; community confirms title + full 4-field schedule. Official guide OFFER example omits event — contradiction.
- callToAction: "Ignored for topic type OFFER"; community says invalid (Google adds own "View Offer"). Guide CTA example uses OFFER — contradiction.

## Q4 — MEDIA
- media[] array; "sourceUrl is the only supported data field for a LocalPost MediaItem."
- Max count not documented; community: effectively 1 photo (seog.ai marks OPEN QUESTION).
- sourceUrl = "publicly accessible URL"; failures -> PHOTO_FETCH_FAILED / PHOTO_UPLOAD_FAILED. dataRef unsupported.
- mediaFormat: MEDIA_FORMAT_UNSPECIFIED, PHOTO ("only photos supported"), VIDEO. VIDEO on posts -> HTTP 500 (community).
- Image bounds: JPG/PNG, 10 KB-5 MB, min 250x250, 720x720 recommended.

## Q5 — CallToAction
- actionType: ACTION_TYPE_UNSPECIFIED, BOOK, ORDER, SHOP, LEARN_MORE, SIGN_UP, GET_OFFER (deprecated), CALL.
- url: "should be left unset for Call CTA". Community: required for all except CALL; CALL must omit (uses profile phone).
- No official URL validation spec.

## Q6 — summary / languageCode / scheduledTime
- summary: no length in docs; community 1500-char cap, "Must be at most 1500 characters". No phone/URL in text.
- languageCode: no allowed values/default documented; examples use en-US/en.
- scheduledTime: RFC3339 Timestamp; no horizon documented; state SCHEDULED; delete to cancel; reviewed up front.

## Q7 — ValidationError codes/messages
Official: 400 / INVALID_ARGUMENT / "Request contains an invalid argument."; details.@type=type.googleapis.com/google.mybusiness.v4.ValidationError; errorDetails[]{code, field, message, value, field_index}.
Documented ErrorCode enum: ERROR_CODE_UNSPECIFIED, MISSING_VALUE, INVALID_VALUE, INVALID_CHARACTERS, TOO_MANY_ITEMS, READ_ONLY, OVERLAPPING_RANGES, INVERTED_RANGE, VALUE_OUTSIDE_ALLOWED_RANGE, MISSING_DEPENDENT_FIELD, FIELD_HAS_DEPENDENCIES, UNSUPPORTED_VALUE, EXPIRED_VALUE, PHOTO_FETCH_FAILED, PHOTO_UPLOAD_FAILED, GEOCODE_ERROR, LAT_LNG_*, CATEGORY_NOT_VERIFIED, OPERATION_*, LOCATION_DISABLED_FOR_LOCAL_POST_API, STALE_DATA.
Observed strings: "event is required" (code 2, field event); "Standard local post must have at least a media or summary." (code 2, field summary); "event.schedule.start_date is invalid" / end_date (code 3); "Must be at most 1500 characters"; "Must be at most 58 characters". No GBP "InvalidEventTime" or documented end-before-start/past-date/max-duration errors.

## Sources
1. https://developers.google.com/my-business/reference/rest/v4/accounts.locations.localPosts (official)
2. https://developers.google.com/my-business/reference/rest/v4/accounts.locations.localPosts/create (official)
3. https://developers.google.com/my-business/content/posts-data (official guide)
4. https://developers.google.com/my-business/reference/rest/v4/accounts.locations.media (official)
5. https://developers.google.com/my-business/reference/rest/v4/Date (official)
6. https://developers.google.com/my-business/reference/rpc/google.mybusiness.v4 (official ValidationError/ErrorCode)
7. https://github.com/googleapis/google-api-nodejs-client/issues/3007 (community)
8. https://stackoverflow.com/questions/67247554/ (community)
9. https://community.n8n.io/t/problem-with-google-business-profile-event-date-format-in-n8n/221574 (community)
10. https://learn.seog.ai/reference/write-limits-and-failure-modes (community probes)
11. https://support.google.com/business/thread/34485360/ (Google forum)
