"""Job table — single source of truth for job execution lifecycle.

Postgres owns whether and when a job runs; the domain table owns what.
See docs/specs/2026-10-10-unified-job-processing-design.md §C.2
"""

import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import DateTime, Enum as SAEnum, Integer, Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ...database import Base
from .types import JobLane, JobType


class JobStatus(str, Enum):
    accepted = "accepted"
    queued = "queued"
    running = "running"
    retrying = "retrying"
    blocked = "blocked"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"
    dead = "dead"


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # RBAC-era convention: every query filters on tenant_id.
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)

    job_type: Mapped[str] = mapped_column(
        SAEnum(*[jt.value for jt in JobType], name="job_type")
    )
    lane: Mapped[str] = mapped_column(
        SAEnum(*[jl.value for jl in JobLane], name="job_lane"), index=True
    )
    status: Mapped[str] = mapped_column(
        SAEnum(
            *[s.value for s in JobStatus],
            name="job_status",
        ),
        default=JobStatus.accepted.value,
        server_default=JobStatus.accepted.value,
        index=True,
    )

    # Lower sorts first: 0 = interactive lane, 100 = bulk.
    priority: Mapped[int] = mapped_column(Integer, default=50, server_default="50")

    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Caller-supplied dedupe. NULL means "never dedupe".
    idempotency_key: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    # The domain object this job acts on — the domain table keeps the truth.
    subject_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    subject_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Kafka partition key — stored so a replay uses the identical key.
    lane_key: Mapped[str] = mapped_column(String(64))

    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    next_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    # Latest moment this job may still run. A job scheduled beyond its
    # deadline becomes due AT the deadline, so a backlog is worked through in
    # order instead of bursting late; a job picked up after its deadline is
    # cancelled rather than run late.
    hard_deadline_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Lease so a crashed worker's job is reclaimable.
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lease_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Written BEFORE the external call, so a crash mid-call is recoverable.
    external_intent: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    external_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_jobs_tenant_idempotency",
        ),
        # The claim query's covering index — same idiom as posts/media.
        Index("ix_jobs_due", "status", "next_run_at"),
        Index("ix_jobs_lane_due", "lane", "status", "next_run_at"),
        Index("ix_jobs_lease", "status", "lease_expires_at"),
        # Retention deletes terminal rows by status + created_at. The claim
        # indexes above are ordered by next_run_at, so they cannot serve the
        # sweep — it would scan the whole jobs table every hour.
        Index("ix_jobs_status_created", "status", "created_at"),
        # The reaper finds overdue jobs by deadline. Name matches the
        # migration so a models-only rebuild produces the same index.
        Index("ix_jobs_hard_deadline", "hard_deadline_at"),
    )


class JobLaneHeartbeat(Base):
    """One row per lane: who is running it and when it was last seen.

    A stuck lane is invisible otherwise — the queue simply stops moving and
    nobody notices until a merchant complains. The runner refreshes its row
    on every tick; the reaper reports lanes that went quiet.
    """

    __tablename__ = "job_lane_heartbeats"

    lane: Mapped[str] = mapped_column(String(32), primary_key=True)
    worker_id: Mapped[str] = mapped_column(String(64))
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    jobs_claimed: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        # Name matches the migration's raw CREATE INDEX.
        Index("ix_job_lane_heartbeats_last_seen", "last_seen_at"),
    )
