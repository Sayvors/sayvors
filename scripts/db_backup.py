#!/usr/bin/env python3
"""Database backup script for Sayvors production.

Dumps the production PostgreSQL database (configured via DATABASE_URL) and
uploads the compressed SQL dump to an S3 bucket.

Usage:

    # One-off backup
    python scripts/db_backup.py

    # Scheduled (cron / ECS scheduled task / Lambda)
    0 2 * * * /usr/bin/python3 /opt/sayvors/scripts/db_backup.py

Environment variables:

    DATABASE_URL        PostgreSQL connection string (required)
    S3_DOCS_BUCKET      S3 bucket for backups (falls back to AWS_S3_BUCKET)
    AWS_REGION          AWS region (default eu-north-1)
    AWS_S3_ENDPOINT_URL Optional S3-compatible endpoint override

Exit codes:

    0   Backup uploaded successfully
    1   Backup failed (missing env, dump failed, upload failed)

The dump is compressed with gzip and named
``sayvors-db-YYYY-MM-DDTHH-MM-SS.sql.gz`` in the bucket root.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name) or default


def _require_env(name: str) -> str:
    value = _env(name)
    if not value:
        print(f"ERROR: {name} environment variable is required", file=sys.stderr)
        sys.exit(1)
    return value


async def _pg_dump(tmpdir: Path) -> Path:
    """Run pg_dump into tmpdir. Returns the path to the dump file."""
    database_url = _require_env("DATABASE_URL")
    dump_path = tmpdir / "dump.sql"

    proc = await asyncio.create_subprocess_exec(
        "pg_dump",
        database_url,
        "--no-owner",
        "--no-privileges",
        "--format=custom",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        err = stderr.decode() if stderr else ""
        print(f"pg_dump failed: {err}", file=sys.stderr)
        raise RuntimeError("pg_dump failed")

    dump_path.write_bytes(stdout)
    return dump_path


async def _gzip(path: Path) -> Path:
    """Gzip a file in place. Returns path to .gz file."""
    gz_path = path.with_suffix(path.suffix + ".gz")
    proc = await asyncio.create_subprocess_exec(
        "gzip",
        "-k",
        "-f",
        str(path),
    )
    await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError("gzip failed")
    return gz_path


async def _upload_to_s3(
    file_path: Path,
    bucket: str,
    s3_key: str,
    region: str,
    endpoint_url: str | None,
) -> None:
    """Upload a file to S3."""
    import boto3
    from botocore.config import Config

    s3_client = boto3.client(
        "s3",
        config=Config(retries={"max_attempts": 3}),
        endpoint_url=endpoint_url,
        region_name=region,
    )
    s3_client.upload_file(
        Filename=str(file_path),
        Bucket=bucket,
        Key=s3_key,
        ExtraArgs={"ServerSideEncryption": "AES256"},
    )


async def backup_once() -> int:
    """Run one pg_dump → S3 backup cycle. Returns exit code."""
    database_url = _require_env("DATABASE_URL")
    bucket = _env("S3_DOCS_BUCKET") or _env("AWS_S3_BUCKET") or ""
    if not bucket:
        print(
            "ERROR: S3_DOCS_BUCKET (or AWS_S3_BUCKET) environment variable is required",
            file=sys.stderr,
        )
        return 1

    region = _env("AWS_REGION", "eu-north-1")
    endpoint_url = _env("AWS_S3_ENDPOINT_URL") or None

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    dump_name = f"sayvors-db-{timestamp}.sql.gz"

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            dump_path = await _pg_dump(Path(tmpdir))
        except RuntimeError as e:
            print(f"{e}", file=sys.stderr)
            return 1

        size_mb = dump_path.stat().st_size / (1024 * 1024)
        print(f"Dumped {size_mb:.2f} MB")

        try:
            gz_path = await _gzip(dump_path)
        except RuntimeError as e:
            print(f"{e}", file=sys.stderr)
            return 1

        s3_key = f"backups/{gz_path.name}"
        print(f"Uploading to s3://{bucket}/{s3_key} ...")
        try:
            await _upload_to_s3(gz_path, bucket, s3_key, region, endpoint_url)
        except Exception as e:
            print(f"S3 upload failed: {e}", file=sys.stderr)
            return 1

        print(f"Backup complete: s3://{bucket}/{s3_key}")
        return 0


def main() -> None:
    exit_code = asyncio.run(backup_once())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()