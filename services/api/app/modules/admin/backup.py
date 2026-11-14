"""Database backup service for the admin console.

Runs ``pg_dump`` → gzip → S3 upload (the same pipeline as
``scripts/db_backup.py`` but in-process so the admin API and the worker
scheduler can drive it), lists S3 object versions, and supports deleting
objects. Schedule config lives in ``admin_backup_config``; every attempt is
recorded in ``admin_backup_runs`` so the admin page shows history even when
S3 is unreachable.
"""
from __future__ import annotations

import asyncio
import logging
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from .models import AdminBackupConfig, AdminBackupRun

logger = logging.getLogger(__name__)

BACKUP_PREFIX = "backups/"
DEFAULT_INTERVAL_HOURS = 24
SCHEDULE_TICK_SECONDS = 60

# Session factory indirection (same pattern as billing modules): the worker
# scheduler and the admin background task run outside a request session, and
# tests swap this for the in-memory test DB.
_session_factory = None


def get_session_factory():
    global _session_factory
    if _session_factory is None:
        from ...database import async_session

        _session_factory = async_session
    return _session_factory


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

async def _get_config_row(db: AsyncSession, *, for_update: bool = False) -> AdminBackupConfig:
    """Return the singleton config row, creating it with defaults if needed."""
    stmt = select(AdminBackupConfig).where(AdminBackupConfig.id == "default")
    if for_update:
        stmt = stmt.with_for_update()
    cfg = (await db.execute(stmt)).scalar_one_or_none()
    if cfg is None:
        cfg = AdminBackupConfig(id="default")
        db.add(cfg)
        await db.flush()
    return cfg


async def get_config(db: AsyncSession) -> dict:
    cfg = await _get_config_row(db)
    return {
        "enabled": bool(cfg.enabled),
        "interval_hours": cfg.interval_hours,
        "bucket": cfg.bucket or settings.S3_DOCS_BUCKET or "",
        "region": cfg.region or "eu-north-1",
        "last_run_at": cfg.last_run_at.isoformat() if cfg.last_run_at else None,
        "next_run_at": cfg.next_run_at.isoformat() if cfg.next_run_at else None,
    }


async def update_config(db: AsyncSession, *, enabled: bool, interval_hours: int,
                        bucket: str | None, region: str | None) -> dict:
    if interval_hours < 1:
        raise ValueError("interval_hours must be >= 1")
    cfg = await _get_config_row(db, for_update=True)
    cfg.enabled = enabled
    cfg.interval_hours = interval_hours
    if bucket is not None:
        cfg.bucket = bucket.strip() or None
    if region is not None:
        cfg.region = region.strip() or "eu-north-1"
    if enabled and cfg.next_run_at is None:
        cfg.next_run_at = datetime.now(timezone.utc) + timedelta(hours=interval_hours)
    await db.commit()
    return await get_config(db)


# ---------------------------------------------------------------------------
# S3 helpers
# ---------------------------------------------------------------------------

def _s3_client(region: str):
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        raise RuntimeError("boto3 is not installed; cannot manage S3 backups")
    return boto3.client("s3", region_name=region, config=Config(retries={"max_attempts": 3}))


def _resolve_bucket_region(cfg: AdminBackupConfig) -> tuple[str, str]:
    bucket = cfg.bucket or settings.S3_DOCS_BUCKET or ""
    if not bucket:
        raise ValueError("No S3 backup bucket configured (set S3_DOCS_BUCKET or admin config)")
    region = cfg.region or settings.AWS_REGION or "eu-north-1"
    return bucket, region


# ---------------------------------------------------------------------------
# Backup execution
# ---------------------------------------------------------------------------

def _libpq_database_url() -> str:
    """Convert the asyncpg URL to a plain postgresql:// URL pg_dump accepts."""
    url = settings.DATABASE_URL
    if url.startswith("postgresql+asyncpg://"):
        url = "postgresql://" + url[len("postgresql+asyncpg://"):]
    elif url.startswith("postgresql+psycopg://"):
        url = "postgresql://" + url[len("postgresql+psycopg://"):]
    return url


async def _pg_dump(tmpdir: Path) -> Path:
    dump_path = tmpdir / "dump.sql"
    proc = await asyncio.create_subprocess_exec(
        "pg_dump",
        _libpq_database_url(),
        "--no-owner",
        "--no-privileges",
        "--format=custom",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"pg_dump failed: {stderr.decode(errors='ignore')[:500]}")
    dump_path.write_bytes(stdout)
    return dump_path


async def _gzip(path: Path) -> Path:
    gz_path = path.with_suffix(path.suffix + ".gz")
    proc = await asyncio.create_subprocess_exec("gzip", "-k", "-f", str(path))
    await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError("gzip failed")
    return gz_path


async def run_backup(db: AsyncSession, trigger: str = "manual") -> dict:
    """Run one backup cycle; returns the run row summary (never raises).

    Failures are recorded on the run row so the admin page can surface the
    error text instead of silently dropping the attempt.
    """
    run_id = str(uuid.uuid4())
    run = AdminBackupRun(id=run_id, trigger_type=trigger, status="running")
    db.add(run)
    await db.commit()

    key = None
    try:
        cfg = await _get_config_row(db, for_update=True)
        bucket, region = _resolve_bucket_region(cfg)

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
        key = f"{BACKUP_PREFIX}sayvors-db-{timestamp}.sql.gz"

        with tempfile.TemporaryDirectory() as tmpdir:
            dump_path = await _pg_dump(Path(tmpdir))
            gz_path = await _gzip(dump_path)
            size = gz_path.stat().st_size
            client = _s3_client(region)
            client.upload_file(
                Filename=str(gz_path),
                Bucket=bucket,
                Key=key,
                ExtraArgs={"ServerSideEncryption": "AES256"},
            )

        now = datetime.now(timezone.utc)
        cfg.last_run_at = now
        cfg.next_run_at = now + timedelta(hours=cfg.interval_hours)
        run.status = "success"
        run.backup_key = key
        run.size_bytes = size
        run.finished_at = now
        await db.commit()
        logger.info("Backup %s complete: s3://%s/%s (%d bytes)", trigger, bucket, key, size)
        return {"id": run_id, "status": "success", "backup_key": key, "size_bytes": size}
    except Exception as e:  # noqa: BLE001 — never raise out of a backup attempt
        now = datetime.now(timezone.utc)
        run.status = "failed"
        run.backup_key = key
        run.error = f"{type(e).__name__}: {str(e)[:500]}"
        run.finished_at = now
        await db.commit()
        logger.error("Backup %s failed: %s", trigger, run.error)
        return {"id": run_id, "status": "failed", "backup_key": key, "error": run.error}


# ---------------------------------------------------------------------------
# Listing / deletion
# ---------------------------------------------------------------------------

async def list_backups(db: AsyncSession) -> dict:
    cfg = await _get_config_row(db)
    bucket, region = None, None
    try:
        bucket, region = _resolve_bucket_region(cfg)
    except ValueError:
        bucket, region = None, None

    objects: dict[str, dict] = {}
    if bucket:
        try:
            client = _s3_client(region)
            paginator = client.get_paginator("list_object_versions")
            for page in paginator.paginate(Bucket=bucket, Prefix=BACKUP_PREFIX):
                for v in page.get("Versions", []):
                    key = v["Key"]
                    entry = objects.setdefault(key, {"key": key, "versions": []})
                    entry["versions"].append({
                        "version_id": v.get("VersionId", "null"),
                        "is_latest": bool(v.get("IsLatest", True)),
                        "size_bytes": v.get("Size", 0),
                        "last_modified": v.get("LastModified"),
                    })
        except Exception as e:  # noqa: BLE001
            logger.warning("S3 list_object_versions failed: %s", e)

    runs = (await db.execute(
        select(AdminBackupRun).order_by(AdminBackupRun.started_at.desc())
    )).scalars().all()

    run_by_key: dict[str, AdminBackupRun] = {}
    for r in runs:
        if r.backup_key and r.backup_key not in run_by_key:
            run_by_key[r.backup_key] = r

    payload_objects = []
    for key, entry in objects.items():
        versions = entry["versions"]
        versions.sort(key=lambda x: x["last_modified"] or datetime.min, reverse=True)
        latest = next((v for v in versions if v["is_latest"]), versions[0] if versions else None)
        run = run_by_key.get(key)
        payload_objects.append({
            "key": key,
            "versions": versions,
            "latest_size_bytes": latest["size_bytes"] if latest else None,
            "latest_modified": latest["last_modified"] if latest else None,
            "run_id": run.id if run else None,
            "status": run.status if run else None,
            "trigger": run.trigger_type if run else None,
            "run_started_at": run.started_at.isoformat() if run else None,
            "error": run.error if run else None,
        })

    # Runs whose S3 object was already deleted or never uploaded stay visible.
    known_keys = set(objects)
    oldest_runs = sorted(runs, key=lambda r: r.started_at, reverse=True)
    for r in oldest_runs:
        if r.backup_key and r.backup_key not in known_keys:
            payload_objects.append({
                "key": r.backup_key,
                "versions": [],
                "latest_size_bytes": r.size_bytes,
                "latest_modified": None,
                "run_id": r.id,
                "status": r.status,
                "trigger": r.trigger_type,
                "run_started_at": r.started_at.isoformat(),
                "error": r.error,
            })

    payload_objects.sort(key=lambda o: o["run_started_at"] or "", reverse=True)
    return {"config": await get_config(db), "objects": payload_objects}


async def delete_backup(db: AsyncSession, key: str, version_id: str | None = None) -> dict:
    cfg = await _get_config_row(db)
    bucket, region = _resolve_bucket_region(cfg)
    client = _s3_client(region)

    deleted = 0
    if version_id and version_id != "null":
        client.delete_object(Bucket=bucket, Key=key, VersionId=version_id)
        deleted = 1
    else:
        # Delete every version so the object is fully gone (a plain delete only
        # adds a delete marker over the latest version).
        paginator = client.get_paginator("list_object_versions")
        for page in paginator.paginate(Bucket=bucket, Prefix=key):
            for v in page.get("Versions", []):
                if v["Key"] == key:
                    client.delete_object(Bucket=bucket, Key=key, VersionId=v["VersionId"])
                    deleted += 1
            for v in page.get("DeleteMarkers", []):
                if v["Key"] == key:
                    client.delete_object(Bucket=bucket, Key=key, VersionId=v["VersionId"])
                    deleted += 1

    await db.execute(
        update(AdminBackupRun)
        .where(AdminBackupRun.backup_key == key)
        .values(status="deleted", finished_at=datetime.now(timezone.utc))
    )
    await db.commit()
    logger.info("Deleted backup s3://%s/%s (%d versions)", bucket, key, deleted)
    return {"key": key, "deleted_versions": deleted}


async def download_url(db: AsyncSession, key: str, version_id: str | None = None) -> str:
    cfg = await _get_config_row(db)
    bucket, region = _resolve_bucket_region(cfg)
    client = _s3_client(region)
    params = {"Bucket": bucket, "Key": key}
    if version_id and version_id != "null":
        params["VersionId"] = version_id
    return client.generate_presigned_url(
        "get_object", Params=params, ExpiresIn=300
    )


# ---------------------------------------------------------------------------
# Worker scheduler
# ---------------------------------------------------------------------------

async def run_backup_standalone(trigger: str = "manual") -> dict:
    """Open a fresh session and run one backup cycle (background/scheduler use)."""
    async with get_session_factory()() as db:
        return await run_backup(db, trigger=trigger)


async def _scheduler_tick() -> None:
    async with get_session_factory()() as db:
        try:
            cfg = await _get_config_row(db, for_update=True)
        except Exception:
            return
        if not cfg.enabled:
            return
        now = datetime.now(timezone.utc)
        if cfg.next_run_at is not None and cfg.next_run_at > now:
            return
        # Claim the due run under the row lock so two replicas cannot both
        # fire it; the long backup runs after the lock is released.
        cfg.next_run_at = now + timedelta(hours=cfg.interval_hours)
        await db.commit()
    await run_backup_standalone(trigger="scheduled")


async def run_db_backup_scheduler() -> None:
    """Background loop: check the schedule every minute."""
    while True:
        try:
            await _scheduler_tick()
        except Exception as e:  # noqa: BLE001 — loop must never die
            logger.exception("Backup scheduler tick failed: %s", e)
        await asyncio.sleep(SCHEDULE_TICK_SECONDS)
