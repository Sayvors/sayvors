# AI-Reply Throughput Runbook

**Target:** 10k msg/min (~167 msg/s) sustained inbound AI replies  
**Current:** ~2 msg/s per worker replica  
**Gap:** ~83× headroom needed

## Architecture

The inbound AI-reply pipeline is:

```
Meta webhook
  -> meta_webhook_events + event_outbox row (one Postgres transaction)
  -> outbox relay publishes to meta-events Kafka topic
  -> meta_events_worker (Kafka consumer group meta-events-replier)
    -> _process_event -> handlers (_handle_message_received, etc.)
    -> LLM reply via llm/gateway.py (budgeted: check_feature + credit reserve)
    -> adapter.send_text_message() -> Meta Cloud API
```

Kafka topic `meta-events` is provisioned with **12 partitions**. The consumer
group `meta-events-replier` balances those partitions across worker replicas.

## Scaling knob: WORKER_LOOPS

The worker entrypoint (`python -m app.workers`) starts every registered loop
by default. To run only the AI-reply loop:

```bash
WORKER_LOOPS=meta-events-ai-replies python -m app.workers
```

Unknown loop names fail fast (`SystemExit`), so a typo'd env var cannot
silently run nothing.

The default (unset `WORKER_LOOPS`) starts every loop on one process — the
single-container dev topology. For production, split by role:

| Role | WORKER_LOOPS | Purpose |
|------|-------------|---------|
| API | `RUN_BACKGROUND_WORKERS=false` | HTTP only, no loops |
| AI worker | `meta-events-ai-replies,escalation-sweeps` | Inbound replies + 24h resume |
| General worker | `google-reviews-auto-reply,lead-actions,post-publisher,analytics-consumer,...` | Everything else |

Multiple AI worker replicas can run in parallel; Kafka rebalances the 12
partitions across them.

## Throughput math

| Metric | Value |
|--------|-------|
| Current per-worker | ~2 msg/s (~120 msg/min) |
| Target | 10k msg/min (~167 msg/s) |
| Partitions | 12 (one consumer per partition max) |
| Workers needed | ceil(167 / 2) = ~84 AI worker replicas |

The 2 msg/s figure is dominated by:
1. Poll interval + claim latency (outbox -> Kafka relay)
2. LLM generation time (budgeted: reserve + settle per call)
3. Meta Cloud API send latency
4. One message per poll (`max_poll_records=1`) keeps offsets ordered

## First batching candidate: ingress commits

The webhook ingress commits per event (~4 round trips: begin, insert outbox,
insert webhook row, commit). At 10k msg/min that's ~40k commit round trips/min
just for ingress. Batching multiple webhook events into one Postgres
transaction is the first throughput candidate:

```python
# Current: one transaction per webhook event
# Future: N events in one transaction, one commit
```

This does not change the consumer path — only the ingress publisher.

## Runbook: scaling up

### 1. Verify current throughput

```bash
# Check consumer lag (should be near 0 in steady state)
kafka-consumer-groups --bootstrap-server kafka:9092 \
  --describe --group meta-events-replier

# Check outbox backlog (should be near 0)
psql -c "SELECT status, count(*) FROM event_outbox WHERE event_type LIKE 'meta.%' GROUP BY status;"
```

### 2. Add AI worker replicas

```bash
# On each AI worker host:
WORKER_LOOPS=meta-events-ai-replies,escalation-sweeps \
python -m app.workers
```

Start with 2-4 replicas, then double until consumer lag stays near 0 under
load.

### 3. Watch for rebalancing

Kafka rebalances partitions when consumers join/leave. During rebalance,
message processing pauses briefly. Scale in steps (add 2-4 replicas at a
time) and wait for lag to clear between steps.

### 4. When partitions are the bottleneck

All 12 partitions are consumed by the group. If you need more than 12
consumers (one per partition), you must increase partition count:

```bash
kafka-topics --bootstrap-server kafka:9092 \
  --alter --topic meta-events --partitions 24
```

Increasing partitions requires the consumer group to rebalance. Plan for a
brief processing pause.

## Runbook: scaling down

Reduce replicas in steps. Kafka will rebalance partitions to remaining
consumers. Consumer lag may rise briefly during rebalance but should clear.

## Monitoring

| Metric | Healthy | Alert threshold |
|--------|---------|-----------------|
| Consumer lag | ~0 | > 100 for 5 min |
| Outbox backlog (meta.*) | ~0 | > 1000 for 5 min |
| AI reply latency (p95) | < 5s | > 15s |
| Worker errors/min | ~0 | > 10 |

## Related

- `docs/operations/workers-and-jobs.md` — worker startup and loop selection
- `docs/database/README.md` — PgBouncer + reader URL config
- M-9(d): composite index on `llm_usage_events(tenant_id, created_at)` and
  GIN trigram indexes on `review_insights` — already applied
  (migrations `f5a8c2d6e9b14371`, `f5a8c2d6e9b14372`)
