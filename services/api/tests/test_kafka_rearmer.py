"""Kafka re-arm: a boot-time broker blip must not red-light the API forever.

The producer/consumer availability flags are process-global latches. The API
process tries Kafka once at startup; on failure it latches offline, and before
this fix nothing in the API process ever re-armed it — run_kafka_rearmer only
ran in the worker deployment. The admin Logs page (served by the API) then
showed Kafka red with "producer not connected (outbox fallback active)" while
the worker next to it was connected and healthy.
"""
import pytest

from app.modules.kafka import client as kafka_client


def _reset_state():
    kafka_client._producer_available = True
    kafka_client._producer_marked_unavailable_at = 0.0
    kafka_client._consumer_available.clear()
    kafka_client._consumer_marked_unavailable_at.clear()


@pytest.fixture(autouse=True)
def _clean_kafka_flags():
    _reset_state()
    yield
    _reset_state()


@pytest.mark.asyncio
async def test_rearm_recovers_a_latched_offline_producer():
    kafka_client.mark_kafka_unavailable()
    assert kafka_client.is_kafka_available() is False

    assert await kafka_client.rearm_kafka_once() is True
    assert kafka_client.is_kafka_available() is True


@pytest.mark.asyncio
async def test_rearm_is_a_noop_when_everything_is_healthy():
    assert await kafka_client.rearm_kafka_once() is False
    assert kafka_client.is_kafka_available() is True


@pytest.mark.asyncio
async def test_rearm_recovers_a_latched_offline_consumer_group():
    kafka_client.mark_kafka_unavailable("meta-events-replier")
    assert kafka_client.is_kafka_available("meta-events-replier") is False

    assert await kafka_client.rearm_kafka_once() is True
    assert kafka_client.is_kafka_available("meta-events-replier") is True
    # Producer flag untouched — a consumer blip must not flip producer state.
    assert kafka_client.is_kafka_available() is True
