"""Dependency health probe shared by /readyz and the container healthchecks.

Extracted so the HTTP endpoint and the `python -m app.healthcheck` container
check cannot drift: a healthcheck that probes something /readyz does not (or
vice versa) is worse than no healthcheck, because it looks correct.

Run as a module it exits 0 when every dependency is reachable and 1 otherwise,
which is exactly the contract Docker's HEALTHCHECK expects.
"""

import asyncio
import sys

CHECK_TIMEOUT_SECONDS = 5.0


async def _probe_database() -> str:
    from sqlalchemy import text

    from .database import engine

    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return "ok"


async def _probe_redis() -> str:
    from .modules.redis.client import get_redis

    redis = await get_redis()
    await redis.ping()
    return "ok"


async def _probe_kafka() -> str:
    from .modules.kafka.client import get_kafka_producer

    await get_kafka_producer()
    return "ok"


async def probe_dependencies() -> dict[str, str]:
    """Probe every dependency, returning per-check status strings.

    Never raises: a failed probe is reported as data, so one dead dependency
    does not hide the state of the others.
    """
    checks: dict[str, str] = {}
    for name, probe in (
        ("database", _probe_database),
        ("redis", _probe_redis),
        ("kafka", _probe_kafka),
    ):
        try:
            checks[name] = await asyncio.wait_for(probe(), CHECK_TIMEOUT_SECONDS)
        except Exception as e:
            checks[name] = f"failed: {e}"
    return checks


async def _amain() -> int:
    checks = await probe_dependencies()
    for name, status in checks.items():
        print(f"{name}: {status}")
    healthy = all(v == "ok" for v in checks.values())
    print("READY" if healthy else "NOT READY")
    return 0 if healthy else 1


def main() -> int:
    try:
        return asyncio.run(_amain())
    except Exception as e:
        print(f"healthcheck crashed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())