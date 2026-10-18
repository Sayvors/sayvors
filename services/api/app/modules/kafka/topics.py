"""Kafka topic provisioning.

Explicit topic creation with real partition counts — replaces auto-create
(which defaults to 1 partition and buys zero throughput when scaling workers).
Run from workers/main.py warmup before any consumer starts.
See docs/specs/2026-10-10-unified-job-processing-design.md §D.1
"""

import logging

from aiokafka.admin import AIOKafkaAdminClient as AIOAdminClient, NewTopic

from ...config import settings

logger = logging.getLogger(__name__)

# Topic plan: (name, partitions, replication_factor)
TOPICS = [
    ("realtime-dispatch", 24, 1),
    ("publishing-dispatch", 12, 1),
    ("media-dispatch", 6, 1),
    ("bulk-dispatch", 6, 1),
    ("realtime-dispatch-dlq", 1, 1),
    ("publishing-dispatch-dlq", 1, 1),
    ("media-dispatch-dlq", 1, 1),
    ("bulk-dispatch-dlq", 1, 1),
    # Existing domains — keep partition counts but provision explicitly.
    ("review-events", 6, 1),
    ("meta-events", 12, 1),
    ("auth-events", 6, 1),
]


async def provision_topics() -> None:
    """Create all topics with explicit partition counts. Idempotent."""
    admin = AIOAdminClient(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        client_id="sayvors-topic-provisioner",
        request_timeout_ms=10000,
    )
    try:
        await admin.start()
        existing = await admin.describe_topics()
        existing_names = {t.get("name") or t.get("topic") for t in existing if t.get("name") or t.get("topic")}

        new_topics = [
            NewTopic(name=name, num_partitions=parts, replication_factor=rf)
            for name, parts, rf in TOPICS
            if name not in existing_names
        ]

        if new_topics:
            await admin.create_topics(new_topics=new_topics, validate_only=False)
            for t in new_topics:
                logger.info("Created Kafka topic: %s (%d partitions)", t.name, t.num_partitions)
        else:
            logger.info("All Kafka topics already provisioned")
    except Exception:
        logger.exception("Kafka topic provisioning failed — topics may already exist or broker down")
        raise
    finally:
        await admin.close()
