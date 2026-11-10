from app.services import stats_history


def _payload(cpu):
    return {
        "cpu_percent": cpu,
        "memory_used_bytes": 1,
        "disk_used_bytes": 2,
        "network_rx_bytes": 3,
        "network_tx_bytes": 4,
        "started_at": "x",
    }


def test_ring_buffer_keeps_only_the_latest_samples():
    stats_history.clear("a")
    for i in range(100):
        stats_history.record("a", _payload(i))
    snap = stats_history.snapshot("a")
    assert len(snap) == stats_history.HISTORY_SAMPLES
    assert snap[-1]["cpu_percent"] == 99
    assert snap[-1]["started_at"] == "x"
    stats_history.clear("a")
    assert stats_history.snapshot("a") == []


def test_servers_have_separate_histories():
    stats_history.clear("a")
    stats_history.clear("b")
    stats_history.record("a", _payload(1))
    assert stats_history.snapshot("b") == []
    stats_history.clear("a")
