# SEC-M2 — Encryption at Rest (Message Content, Contact Phones, Webhook Secrets)

## Overview

Encrypt sensitive data at rest using Fernet (AES-128 in CBC mode with HMAC). Key sources:
- `CHANNEL_ENCRYPTION_KEY` env var (preferred)
- Falls back to `JWT_SECRET`-derived key (SHA-256 of secret)

## What's Encrypted

| Data | File | Column | Method | Lookup Key |
|------|------|--------|--------|------------|
| Message content | `channels/service.py` | `channel_messages.content` | `encrypt()`/`decrypt()` | `contact_phone_hash` |
| Contact phone | `channels/service.py` | `channel_messages.contact_phone_hash` | SHA-256 hash | Direct lookup |
| Webhook secrets | `channels/service.py` | `whatsapp_thread_states.webhook_secret` | `encrypt()`/`decrypt()` | N/A |
| Contact phone hash | `channels/meta/consumer.py` | `channel_messages.contact_phone_hash` | SHA-256 | Indexed for lookups |
| Contact phone hash | `channels/meta/consumer.py` | `whatsapp_thread_states.contact_phone_hash` | SHA-256 | Indexed for lookups |

## Files

| File | Purpose |
|------|---------|
| `app/modules/channels/service.py` | `encrypt_token()` / `decrypt_token()` helpers |
| `app/modules/channels/meta/consumer.py` | All message write/read paths encrypted |
| `app/config.py` | `CHANNEL_ENCRYPTION_KEY` setting |

## Migration

Added `contact_phone_hash` columns to:
- `channel_messages`
- `whatsapp_thread_states`

## Security Properties

- **Fernet**: Authenticated encryption (AES-CBC + HMAC-SHA256)
- **Key rotation**: Rotate `CHANNEL_ENCRYPTION_KEY` every 90 days; re-encrypt on rotation
- **Fallback**: If `CHANNEL_ENCRYPTION_KEY` unset, derives key from `JWT_SECRET` (less ideal, document in prod)
- **Phone lookups**: Hash phone numbers with SHA-256 for lookups without storing plaintext

## Status

✅ Done — all message write/read paths encrypted; `contact_phone_hash` columns added to both tables.
