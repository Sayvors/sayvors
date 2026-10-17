"""Unified job processing module — Phase 0 of the approved design.

Postgres owns execution truth; Kafka owns dispatch only; Redis owns
ephemeral admission control. See docs/specs/2026-10-10-unified-job-processing-design.md
"""
