"""A large download on an idle server is no attack; a packet flood still is."""

from app.services.ddos_detect import Detector


def _levels(packets_per_step: int) -> list[str]:
    det = Detector()
    name = "t"
    now, rx, packets = 0.0, 0, 0
    det.observe(name, now, rx, net={"rx_packets": packets})
    levels = []
    for i in range(40):
        now += 2.0
        if i < 20:
            rx += 2000
            packets += 20
        else:
            rx += 20 * 1024 * 1024
            packets += packets_per_step
        levels.append(det.observe(name, now, rx, net={"rx_packets": packets}).level)
    return levels


def test_download_without_packet_flood_is_not_an_attack() -> None:
    levels = _levels(600)
    assert "attack" not in levels
    assert "watch" in levels


def test_packet_flood_is_still_an_attack() -> None:
    assert "attack" in _levels(60000)
