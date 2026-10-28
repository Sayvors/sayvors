# Bulk Location Edit via CSV

## Overview

Bulk edit allows tenants to update multiple business locations at once using a
CSV file. Download a template pre-filled with current data, edit offline, and
upload to apply.

## Endpoints

### Download template
```
GET /api/v1/locations/bulk-template
```
Returns a CSV file (`locations_bulk_template.csv`) with one row per listing,
pre-filled with current values. Columns:

| Column | Description | Editable |
|---|---|---|
| `listing_id` | Unique listing identifier (required, do not change) | No |
| `name` | Business name | Yes |
| `phone` | Phone number | Yes |
| `website` | Website URL | Yes |
| `description` | Business description | Yes |
| `address` | Address line 1 | Yes |
| `city` | City | Yes |
| `zip_code` | Zip/postal code | Yes |
| `category` | Primary category | Yes |
| `hours_regular` | Regular hours (JSON object) | Yes |
| `special_hours` | Special hours (JSON array) | Yes |
| `opening_date` | Opening date (YYYY-MM-DD) | Yes |
| `attributes` | Business attributes (JSON object) | Yes |
| `service_area` | Service area (comma-separated) | Yes |

### Upload CSV
```
POST /api/v1/locations/bulk-upload
Content-Type: multipart/form-data
```
Upload a CSV file. Returns a per-row report:
```json
{
  "total": 5,
  "success": 4,
  "failed": 1,
  "results": [
    {"row": 2, "listing_id": "abc123", "status": "ok"},
    {"row": 3, "listing_id": "def456", "status": "error", "error": "listing not found or not owned"}
  ]
}
```

### Validation
- File must be `.csv` and UTF-8 encoded.
- Max file size: 5 MB.
- Max rows: 500.
- `listing_id` is required and must belong to the tenant.
- `hours_regular` and `special_hours` must be valid JSON.
- `attributes` must be valid JSON.
- `opening_date` must be `YYYY-MM-DD`.

### Safety
- **Tenant isolation**: only the tenant's own listings can be updated.
- **Per-row atomicity**: one row failure doesn't block others; failed rows are reported.
- **Idempotent**: re-running the same CSV is safe.
- **Google push**: updates flow through `update_profile()`, so description changes push to Google/Localith as usual.

## Hours format

`hours_regular` is a JSON object keyed by day name:
```json
{"Monday": {"open": "09:00", "close": "17:00", "closed": false}, "Sunday": {"closed": true}}
```

`special_hours` is a JSON array:
```json
[{"date": "2026-12-25", "hours": "closed", "reason": "Holiday"}]
```

## Attributes format

```json
{"wheelchair accessible entrance": "true", "free wifi": "true"}
```