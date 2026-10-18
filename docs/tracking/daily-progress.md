# Daily Progress Report

## 2026-10-17
- Docs and tracking updated
- Job queue Phase 0 implemented
- Job queue Phase 1 implemented
- Redis production config + TTL analysis
- Redis implementation docs created
- Billing budget balance TTL added (24h)
- SEC-H1 SSRF fix implemented
- G2 access token to httpOnly cookie implemented
- G2 pushed to development (c80028d)
- G2 test fixes pushed (794443f)
- Production checklist created
- G2 cookie forwarding fix pushed (middleware forwards Set-Cookie from API)
- API_BASE defaults to same-origin proxy on HTTPS dev (tunnel fix)
- COOKIE_DOMAIN default changed to .sayvors.com for cross-subdomain auth
- SEC-M5 SSRF fix in reviewer-photo download (fetch_pinned guard)
- Job queue runner fixes: AIOKafkaAdminClient import, jobs table migration applied locally, Kafka topic provisioning dict access fix (t['name'] not t.name)
- Worker starts cleanly: all 4 job lanes (realtime/publishing/media/bulk) running
- SEC-M2: Encrypt message content, contact phones, webhook secrets at rest

## 2026-10-18
- SEC-H2: LLM rate limit + metering on /llm/chat and /llm/chat/stream (reserve/settle budget)
- PgBouncer support added (config + docker-compose dev + prod)
- Read replica support added (get_db_read + DATABASE_READER_URL)
- integrations/channels/embedsocial.py stub created (unblocks app startup)
- services/api/integrations/storage/s3.py created (S3 backend for media/docs)
- services/api/app/modules/channels/publish/router.py created (POST/GET publish)
- Admin overview stats endpoints added (/overview/stats, /overview/stats/live)
- Admin overview UI rebuilt (window pill, Attention, main facts band, platforms)
- Frontend publish wiring (ConfirmModal, MediaSink, PublishComposer, types, api-publish.ts)
- docs/database/README.md created (writer/reader pattern, PgBouncer, read replica)
- docs/api/endpoints.md updated (admin, storage, publish sections)
- docs/tracking/SEC-M2-ENCRYPTION.md created
- docs/tracking/SEC-M5-REVIEWER-PHOTO.md created
- docs/tracking/OPS-2-OBSERVABILITY.md created
- docs/tracking/PRODUCTION-CHECKLIST.md updated (I-5, I-7, DATABASE_READER_URL, DB_POOL_MODE)
- docs/tracking/action-items.md updated (job queue status built)
- OPS-3: CI test gating added (.github/workflows/ci.yml runs pytest+eslint+tsc before image builds; deploy-staging gated on CI pass)
- All changes pushed to development
- SEC-M2 encryption test alignment: fixed 12 test files for encrypted-at-rest contract
- CI test gating updated: scoped ESLint to changed files, DB pool + Redis fail-open for CI
- Fixed channels/router.py missing decrypt_contact_phone/decrypt_message_content imports
- Fixed embedsocial _post stub for test compatibility
