#!/usr/bin/env python3
"""Database restore script for Sayvors production backup rehearsal.

Downloads a PostgreSQL dump from S3 and restores it into a scratch database.

Usage:

    # Restore from S3 to a local scratch database
    DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/sayvors_test \
    S3_DOCS_BUCKET=my-backups-bucket \
    BACKUP_KEY=backups/sayvors-db-2026-10-21T02-00-00.sql.gz \
    python scripts/db_restore.py

Environment variables:

    DATABASE_URL        Target PostgreSQL connection string (required)
    S3_DOCS_BUCKET      S3 bucket (falls back to AWS_S3_BUCKET)
    BACKUP_KEY          S3 key of the backup to restore (required)
    AWS_REGION          AWS region (default eu-north-1)
    AWS_S3_ENDPOINT_URL Optional S3-compatible endpoint override

Exit codes:

    0   Restore completed successfully
    1   Restore failed

The restore drops and recreates the target database first, so use a scratch
database, never production.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name) or default


def _require_env(name: str) -> str:
    value = _env(name)
    if not value:
        print(f"ERROR: {name} environment variable is required", file=sys.stderr)
        sys.exit(1)
    return value


async def _download_from_s3(
    bucket: str,
    s3_key: str,
    dest: Path,
    region: str,
    endpoint_url: str | None,
) -> None:
    """Download a file from S3."""
    import boto3
    from botocore.config import Config

    s3_client = boto3.client(
        "s3",
        config=Config(retries={"max_attempts": 3}),
        endpoint_url=endpoint_url,
        region_name=region,
    )
    s3_client.download_file(Bucket=bucket, Key=s3_key, Filename=str(dest))


async def _gunzip(path: Path) -> Path:
    """Gunzip a file in place. Returns path to the ungzipped file."""
    sql_path = path.with_suffix("")
    proc = await asyncio.create_subprocess_exec(
        "gunzip",
        "-k",
        "-f",
        str(path),
    )
    await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError("gunzip failed")
    return sql_path


async def _pg_restore(database_url: str, sql_path: Path) -> None:
    """Restore a pg_dump custom-format dump into the target database.

    Drops and recreates the target database first.
    """
    import urllib.parse

    parsed = urllib.parse.urlparse(database_url)
    db_name = parsed.path.lstrip("/")
    if not db_name:
        raise ValueError("DATABASE_URL must include a database name")

    # Drop and recreate the target database
    # Connect to postgres database to drop/recreate target
    admin_url = database_url.rsplit("/", 1)[0] + "/postgres"

    drop_proc = await asyncio.create_subprocess_exec(
        "psql",
        admin_url,
        "-c",
        f"DROP DATABASE IF EXISTS {db_name};",
    )
    await drop_proc.communicate()

    create_proc = await asyncio.create_subprocess_exec(
        "psql",
        admin_url,
        "-c",
        f"CREATE DATABASE {db_name};",
    )
    await create_proc.communicate()
    if create_proc.returncode != 0:
        raise RuntimeError("Failed to create target database")

    # Restore into the target database
    restore_proc = await asyncio.create_subprocess_exec(
        "pg_restore",
        "--no-owner",
        "--no-privileges",
        "-d",
        database_url,
        str(sql_path),
    )
    await restore_proc.communicate()
    if restore_proc.returncode != 0:
        raise RuntimeError("pg_restore failed")


async def restore_once() -> int:
    """Download a backup from S3 and restore it. Returns exit code."""
    database_url = _require_env("DATABASE_URL")
    bucket = _env("S3_DOCS_BUCKET") or _env("AWS_S3_BUCKET") or ""
    if not bucket:
        print(
            "ERROR: S3_DOCS_BUCKET (or AWS_S3_BUCKET) environment variable is required",
            file=sys.stderr,
        )
        return 1
    s3_key = _require_env("BACKUP_KEY")

    region = _env("AWS_REGION", "eu-north-1")
    endpoint_url = _env("AWS_S3_ENDPOINT_URL") or None

    with tempfile.TemporaryDirectory() as tmpdir:
        gz_path = Path(tmpdir) / Path(s3_key).name
        print(f"Downloading s3://{bucket}/{s3_key} ...")
        try:
            await _download_from_s3(bucket, s3_key, gz_path, region, endpoint_url)
        except Exception as e:
            print(f"S3 download failed: {e}", file=sys.stderr)
            return 1

        print("Decompressing ...")
        try:
            sql_path = await _gunzip(gz_path)
        except RuntimeError as e:
            print(f"{e}", file=sys.stderr)
            return 1

        print(f"Restoring into {database_url.rsplit('/', 1)[-1]} ...")
        try:
            await _pg_restore(database_url, sql_path)
        except RuntimeError as e:
            print(f"{e}", file=sys.stderr)
            return 1

        print("Restore complete.")
        return 0


def main() -> None:
    exit_code = asyncio.run(restore_once())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()