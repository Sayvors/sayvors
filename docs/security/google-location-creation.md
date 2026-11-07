# Google location creation

Last updated: 2026-11-07.

## Implementation

Location creation follows Google's duplicate-check workflow:

1. The dashboard collects business name, primary category, storefront address, phone and website.
2. `POST /api/v1/locations/search` calls Google's `googleLocations.search` with the same storefront payload.
3. If a match is claimed by another owner, the UI offers Google's request-access URL and blocks creation of a duplicate.
4. `POST /api/v1/locations` checks locations already managed by the connected account before creation.
5. Sayvors resolves the category through `categories.list` with `languageCode=en` and the address's `regionCode`, then calls `accounts.locations.create` with `validateOnly=true`.
6. The real create call uses a client idempotency `requestId`; only after Google returns the new resource does Sayvors persist the `google_reviews` channel.

## Security invariants

- A connected Google channel supplies the Business Profile account and OAuth tokens; the tenant cannot select an arbitrary account.
- `listing_key` is the Google location id, and a unique-index race reuses the existing channel instead of creating a second one.
- Google create permission is not assumed: 403 responses are surfaced as "must be an owner or manager with create access."
- A 409 from Google means the listing already exists, so the API rejects it rather than saving a local duplicate.
- Search results and Google errors are normalized; raw provider payloads are not rendered to the browser.
- `PIN_DROP_REQUIRED` means Google cannot locate the textual address precisely enough. Sayvors tells the merchant to create/pin it in Google Business Profile instead of guessing coordinates.
