# Sayvors — Tracking Index

This folder is the **single source of truth** for all tracking, audit, and action items.
The historical root-level audits and plans (`SECURITY-AUDIT.md`, `FIXES-NEEDED.md`, `DEEP-SCAN-REPORT.md`, `FIX-PLAN-SCALE.md`, `PENDING-QUEUE.md`) were consolidated here; their root copies were removed on 2026-10-26 so they can no longer contradict the current ledger. Archived originals live in `source-files/`.

## Folders

| Folder | Purpose |
|--------|---------|
| `action-items.md` | **Master consolidated list** — every finding, fix, feature, and flag with status + where it lives |
| `production-later.md` | Items deferred for later (production VM, 3-broker Kafka, Redis HA, etc.) — not actionable today |
| `source-files/` | Copies of original root-level tracking files (kept for reference) |

## Quick status

| Area | Status | Where |
|------|--------|-------|
| Security audit (SECURITY-AUDIT.md) | B+ rating, G1–G9 remaining | `source-files/SECURITY-AUDIT.md` |
| Production readiness (FIXES-NEEDED.md) | 148 findings, A/B/C/D/E phases | `action-items.md` |
| Pending product features (PENDING-QUEUE.md) | Facebook section deferred, tone done, multi-location partial | `action-items.md` |
| Scale fix plan (FIX-PLAN-SCALE.md) | P0–P3 prioritized | `action-items.md` |
| Deep scan (DEEP-SCAN-REPORT.md) | Overall D+, 47/100 | `source-files/` |
| Job queue design | **Built (Phase 0+1)** — lanes, handlers, publish endpoint | `docs/specs/2026-10-10-unified-job-processing-design.md` |

## How to use

1. Read `action-items.md` for the full consolidated list.
2. Items marked **"For later"** are in `production-later.md` — they need a production VM, not your laptop.
3. Items marked **"Do today"** are safe to implement on your current setup (1-broker Kafka, t3.small).
4. Start with job queue Phase 0 (`jobs` table + migration + producer/consumer hardening) — it needs no new infra.
