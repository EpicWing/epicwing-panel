from app.services.ddos_detect import Detector


def test_export_and_restore_roundtrip():
    detector = Detector()
    detector.observe("c", 0.0, 0)
    for i in range(1, 40):
        detector.observe("c", i * 2.0, i * 2000, tx_bytes=i * 1000)
    rows = detector.export_buckets(80.0, 1_000_080.0, 0)
    assert rows

    fresh = Detector()
    fresh.restore(rows, 5.0, 1_000_090.0)
    rx, tx = fresh.history("c", 5.0)
    assert max(rx) == 1000
    assert max(tx) == 500
