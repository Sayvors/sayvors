"""M9: one scrape sees all workers, and p90/p95 are directly readable."""
import os

import pytest

from app import main as app_main


@pytest.mark.skipif(not hasattr(os, "fork"), reason="POSIX fork required")
def test_shared_file_is_visible_in_another_worker():
    """uvicorn imports the app inside each worker; a path-based store must
    still aggregate their writes."""
    if not app_main._METRICS_SHARED:
        pytest.skip("shared metrics store unavailable on this host")
    before = app_main._metrics_snapshot()["count"]
    pid = os.fork()
    if pid == 0:
        app_main._observe_request(0.01)
        os._exit(0)
    os.waitpid(pid, 0)
    assert app_main._metrics_snapshot()["count"] == before + 1


def test_histogram_quantile_interpolates_inside_the_bucket():
    buckets = [0] * len(app_main._METRICS_LATENCY_BUCKETS_SECONDS)
    buckets[6] = 90  # <= 0.5s
    buckets[7] = 10  # <= 1s
    assert app_main._histogram_quantile(0.90, buckets) == 0.5
    assert app_main._histogram_quantile(0.95, buckets) == 0.75


def test_histogram_quantile_is_honest_when_empty():
    empty = [0] * len(app_main._METRICS_LATENCY_BUCKETS_SECONDS)
    assert app_main._histogram_quantile(0.95, empty) is None


def test_observe_request_updates_all_three_counters():
    before = app_main._metrics_snapshot()
    app_main._observe_request(0.03)
    after = app_main._metrics_snapshot()
    assert after["count"] == before["count"] + 1
    assert after["latency_sum"] >= before["latency_sum"] + 0.03
    assert sum(after["buckets"]) == sum(before["buckets"]) + 1


def test_metrics_endpoint_exposes_percentiles(client):
    app_main._observe_request(0.02)
    response = client.get("/metrics")
    assert response.status_code == 200
    body = response.text
    for name in (
        "sayvors_http_request_p90_seconds",
        "sayvors_http_request_p95_seconds",
        "sayvors_http_request_duration_seconds_bucket",
    ):
        assert name in body
