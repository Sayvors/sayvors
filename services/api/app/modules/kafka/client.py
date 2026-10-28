import asyncio
import logging
import time

from aiokafka import AIOKafkaProducer, AIOKafkaConsumer

from ...config import settings

logger = logging.getLogger(__name__)

_producer: AIOKafkaProducer | None = None
_producer_lock = asyncio.Lock()
_producer_available = True
_producer_marked_unavailable_at = 0.0

# Per-consumer-group availability. Keyed by group_id so one lane or
# consumer going down does not disable Kafka for the whole process.
_consumer_available: dict[str, bool] = {}
_consumer_marked_unavailable_at: dict[str, float] = {}
# How long to wait before re-probing a consumer after it was marked
# unavailable. Mirrors the Redis reprobe cooldown.
KAFKA_REPROBE_COOLDOWN_SECONDS = 5.0


def _kafka_security_kwargs() -> dict:
    """Build the security/TLS kwargs for aiokafka clients.

    Defaults reproduce the current self-hosted plaintext setup, so existing
    deployments and local dev are unaffected. Flip the KAFKA_* env vars when
    pointing at a managed cluster (MSK / Confluent Cloud / Google Managed).
    """
    from ...config import settings

    kwargs: dict = {"security_protocol": getattr(settings, "KAFKA_SECURITY_PROTOCOL", "PLAINTEXT")}
    protocol = kwargs["security_protocol"]
    if protocol.startswith("SASL"):
        mech = getattr(settings, "KAFKA_SASL_MECHANISM", "") or ""
        if mech:
            kwargs["sasl_mechanism"] = mech
        user = getattr(settings, "KAFKA_SASL_USERNAME", "") or ""
        pw = getattr(settings, "KAFKA_SASL_PASSWORD", "") or ""
        if user:
            kwargs["sasl_plain_username"] = user
        if pw:
            kwargs["sasl_plain_password"] = pw
    if "SSL" in protocol:
        ca = getattr(settings, "KAFKA_SSL_CA_CERTS", "") or ""
        cert = getattr(settings, "KAFKA_SSL_CERTFILE", "") or ""
        key = getattr(settings, "KAFKA_SSL_KEYFILE", "") or ""
        if ca:
            kwargs["ssl_cafile"] = ca
        if cert:
            kwargs["ssl_certfile"] = cert
        if key:
            kwargs["ssl_keyfile"] = key
    return kwargs


async def get_kafka_producer(*, retry: bool = False) -> AIOKafkaProducer:
    global _producer, _producer_available, _producer_marked_unavailable_at
    if _producer is not None and _producer_available:
        return _producer
    if not _producer_available and not retry:
        if (time.monotonic() - _producer_marked_unavailable_at) < KAFKA_REPROBE_COOLDOWN_SECONDS:
            raise ConnectionError("Kafka producer marked unavailable")
        # Cooldown elapsed — re-probe.
        _producer_marked_unavailable_at = 0.0
        _producer_available = True

    async with _producer_lock:
        if _producer is None:
            _producer = AIOKafkaProducer(
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                client_id="sayvors-api",
                acks="all",
                enable_idempotence=True,
                linger_ms=5,
                compression_type="gzip",
                request_timeout_ms=30000,
                metadata_max_age_ms=5000,
                **_kafka_security_kwargs(),
            )
            try:
                await asyncio.wait_for(_producer.start(), timeout=15.0)
                _producer_available = True
            except Exception as e:
                _producer = None
                _producer_available = False
                _producer_marked_unavailable_at = time.monotonic()
                logger.warning("Kafka producer unavailable (will retry): %s", e)
                raise
    return _producer


def mark_kafka_unavailable(group_id: str | None = None) -> None:
    """Latch Kafka offline for a consumer group (or the producer if None).

    Process-global unavailability is avoided: a blip on one consumer
    disables only that consumer, not every lane.
    """
    global _producer_available, _producer_marked_unavailable_at
    if group_id is None:
        _producer_available = False
        _producer_marked_unavailable_at = time.monotonic()
        logger.warning("Kafka producer marked unavailable, re-probing in %ss", KAFKA_REPROBE_COOLDOWN_SECONDS)
    else:
        _consumer_available[group_id] = False
        _consumer_marked_unavailable_at[group_id] = time.monotonic()
        logger.warning("Kafka consumer %s marked unavailable, re-probing in %ss", group_id, KAFKA_REPROBE_COOLDOWN_SECONDS)


def mark_kafka_available(group_id: str | None = None) -> None:
    global _producer_available
    if group_id is None:
        _producer_available = True
    else:
        _consumer_available[group_id] = True
    logger.info("Kafka %s marked available", group_id or "producer")


def is_kafka_available(group_id: str | None = None) -> bool:
    if group_id is None:
        return _producer_available
    return _consumer_available.get(group_id, True)


async def close_kafka() -> None:
    global _producer
    if _producer is not None:
        try:
            await _producer.stop()
        except Exception:
            pass
        _producer = None


async def create_consumer(
    group_id: str,
    topics: list[str],
    *,
    max_poll_interval_ms: int | None = None,
    session_timeout_ms: int = 30_000,
    max_poll_records: int = 1,
    enable_auto_commit: bool = False,
) -> AIOKafkaConsumer:
    """Create a Kafka consumer with manual offset commit."""
    from ...config import settings

    if max_poll_interval_ms is None:
        max_poll_interval_ms = getattr(settings, "KAFKA_MAX_POLL_INTERVAL_MS", 900000)
    _consumer_available[group_id] = True
    _consumer_marked_unavailable_at.pop(group_id, None)

    consumer = AIOKafkaConsumer(
        *topics,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=group_id,
        enable_auto_commit=enable_auto_commit,
        auto_offset_reset="earliest",
        max_poll_interval_ms=max_poll_interval_ms,
        session_timeout_ms=session_timeout_ms,
        max_poll_records=max_poll_records,
        value_deserializer=lambda b: __import__("json").loads(b.decode()),
        client_id=f"sayvors-{group_id}",
        **_kafka_security_kwargs(),
    )
    await consumer.start()
    return consumer


async def run_kafka_rearmer() -> None:
    """Background prober that re-arms Kafka consumers and producer after an outage."""
    import asyncio

    while True:
        await asyncio.sleep(30)
        global _producer_available
        # Re-latch producer if it was unavailable
        if not _producer_available:
            _producer_available = True
            logger.info("Kafka re-arm prober: producer re-latched, will retry on next call")
        # Re-latch all consumers
        for gid in list(_consumer_available):
            if not _consumer_available.get(gid, True):
                _consumer_available[gid] = True
                logger.info("Kafka re-arm prober: consumer %s re-latched", gid)
