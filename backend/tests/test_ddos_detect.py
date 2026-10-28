from app.services.ddos_detect import STALE_SECONDS, Detector

KIB = 1024
FLOOD = {"lines": 1200, "window_lines": 1200, "sources": 900, "top": 2}


class Feeder:
    """Schickt Frames im Abstand von 2 s mit einer gewünschten Eingangsrate."""

    def __init__(self, det=None, name="a"):
        self.det = det or Detector()
        self.name = name
        self.t = 0.0
        self.rx = 0
        self.pk = 0
        self.det.observe(name, self.t, 0, {"rx_packets": 0})

    def step(self, rate, net=None, console=None, pps=10):
        self.t += 2.0
        self.rx += int(rate * 2)
        if net is None:
            self.pk += int(pps * 2)
            net = {"rx_packets": self.pk}
        return self.det.observe(self.name, self.t, self.rx, net, console)


def test_learns_first():
    f = Feeder()
    for _ in range(5):
        verdict = f.step(100 * KIB)
    assert verdict.level == "learning"


def test_normal_after_learning():
    f = Feeder()
    for _ in range(20):
        verdict = f.step(100 * KIB)
    assert verdict.level == "normal"
    assert verdict.reasons == ()
    assert not verdict.alert


def test_chatty_console_is_normal():
    f = Feeder()
    chat = {"lines": 40, "window_lines": 40, "sources": 10, "top": 4}
    for _ in range(20):
        verdict = f.step(100 * KIB, console=chat)
    assert verdict.level == "normal"


def test_traffic_spike_alerts_once():
    f = Feeder()
    for _ in range(20):
        f.step(100 * KIB)
    verdicts = [f.step(5 * 1024 * KIB, pps=30000) for _ in range(4)]
    assert sum(v.alert for v in verdicts) == 1
    assert verdicts[-1].level == "attack"
    assert verdicts[-1].reasons


def test_long_attack_does_not_become_normal():
    f = Feeder()
    for _ in range(20):
        f.step(100 * KIB)
    for _ in range(200):
        verdict = f.step(5 * 1024 * KIB, pps=30000)
    assert verdict.level == "attack"


def test_counter_reset_is_not_an_attack():
    f = Feeder()
    for _ in range(20):
        f.step(100 * KIB)
    f.rx = 0  # Container neu gestartet, Zähler beginnen von vorn
    verdict = f.step(100 * KIB)
    assert verdict.level == "normal"
    assert not verdict.alert


def test_console_flood_alerts_even_while_learning():
    f = Feeder()
    verdict = f.step(0, console=FLOOD)
    assert verdict.level == "attack"
    assert verdict.alert
    assert "Console flooded" in verdict.reasons[0]


def test_dropped_packets_are_detected():
    f = Feeder()
    f.step(0, net={"rx_dropped": 0})
    verdict = f.step(0, net={"rx_dropped": 5000})
    assert verdict.level == "attack"
    assert "dropped" in verdict.reasons[0]


def test_snapshot_and_forget():
    det = Detector()
    f = Feeder(det, "x")
    f.step(100 * KIB)
    snap = det.snapshot("x", f.t + STALE_SECONDS + 1)
    assert snap is not None
    assert snap["age"] > STALE_SECONDS
    det.forget("x")
    assert det.snapshot("x", f.t) is None


def test_servers_are_judged_separately():
    det = Detector()
    a = Feeder(det, "a")
    b = Feeder(det, "b")
    for _ in range(20):
        a.step(100 * KIB)
        b.step(100 * KIB)
    alerts_a = []
    for _ in range(4):
        alerts_a.append(a.step(5 * 1024 * KIB, pps=30000).alert)
        verdict_b = b.step(100 * KIB)
        assert verdict_b.level == "normal"
        assert not verdict_b.alert
    assert sum(alerts_a) == 1
    assert det.snapshot("a", a.t)["level"] == "attack"
    assert det.snapshot("b", b.t)["level"] == "normal"
    det.forget("a")
    assert det.snapshot("b", b.t) is not None


def test_console_flood_on_one_server_leaves_others_alone():
    det = Detector()
    a = Feeder(det, "a")
    b = Feeder(det, "b")
    assert a.step(0, console=FLOOD).alert
    assert b.step(0).level != "attack"
