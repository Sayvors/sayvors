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
- API_BASE defaults to same-origin proxy on HTTPS dev (tunnel fix)
- SEC-M5 SSRF fix in reviewer-photo download (fetch_pinned guard)
- Job queue runner fixes: AIOKafkaAdminClient import, jobs table migration applied locally, Kafka topic provisioning dict access fix (t['name'] not t.name)
- Worker starts cleanly: all 4 job lanes (realtime/publishing/media/bulk) running
