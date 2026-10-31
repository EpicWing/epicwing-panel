"""Detection of unusual incoming traffic and console floods per server.

Pure logic without database and network. The agent sends every few seconds
cumulative counters, from which rates and a level are computed here.
"""

from collections import deque
from dataclasses import dataclass, field
from statistics import median
from typing import Any

LEVELS = ("learning", "normal", "watch", "attack")

HISTORY_POINTS = 300  # 10 minutes at 2 s steps
RECENT_POINTS = 3
MIN_SAMPLES = 15
MIN_INTERVAL = 0.5  # shorter gaps do not give a usable rate
STALE_SECONDS = 15.0
HISTORY_SECONDS = 3600
BUCKET_SECONDS = 10

WATCH_FACTOR = 3
ATTACK_FACTOR = 10

BYTES_WATCH, BYTES_ATTACK = 512 * 1024, 2 * 1024 * 1024  # Bytes pro Sekunde
PPS_WATCH, PPS_ATTACK = 1_000, 10_000  # Pakete pro Sekunde
DROP_WATCH, DROP_ATTACK = 200, 2_000  # verworfene Pakete pro Sekunde
LINES_WATCH, LINES_ATTACK = 100, 500  # Konsolenzeilen pro Sekunde
SOURCES_WATCH, SOURCES_ATTACK = 30, 150  # verschiedene Quellen pro Sekunde
SOURCES_MIN_LINES = 30  # sources only count from this line rate

# Counters that go up when packets are refused or dropped.
DROP_KEYS = (
    "rx_dropped",
    "ip_in_hdr_errors",
    "ip_in_addr_errors",
    "tcp_listen_drops",
    "tcp_listen_overflows",
    "tcp_syncookies_sent",
    "tcp_in_errs",
    "udp_no_ports",
    "udp_in_errors",
    "udp_rcvbuf_errors",
)


@dataclass(frozen=True)
class Verdict:
    level: str
    reasons: tuple[str, ...]
    alert: bool  # True exactly when it switches to "attack"


class _Series:
    """Latest values and baseline of a rate."""

    def __init__(self) -> None:
        self.recent: deque[float] = deque(maxlen=RECENT_POINTS)
        self.history: deque[float] = deque(maxlen=HISTORY_POINTS)

    def add(
        self, rate: float, watch_floor: float, attack_floor: float
    ) -> tuple[int, float | None, float]:
        """Returns (level as index in LEVELS, usual rate, factor). 0 = still learning."""
        self.recent.append(rate)
        if len(self.history) < MIN_SAMPLES:
            self.history.append(rate)
            return 0, None, 1.0
        recent = sum(self.recent) / len(self.recent)
        usual = float(median(self.history))
        factor = recent / max(usual, 1.0)
        index = 1
        if recent >= attack_floor and factor >= ATTACK_FACTOR:
            index = 3
        elif recent >= watch_floor and factor >= WATCH_FACTOR:
            index = 2
        if index < 2:
            # Unusual values do not go into the baseline, otherwise a
            # long attack would become the normal state at some point.
            self.history.append(rate)
        return index, usual, factor


@dataclass
class _State:
    at: float
    rx_bytes: int
    counters: dict[str, int]
    bytes: _Series = field(default_factory=_Series)
    packets: _Series = field(default_factory=_Series)
    samples: int = 0
    level: str = "learning"
    reasons: tuple[str, ...] = ()
    rates: dict[str, float | None] = field(default_factory=dict)
    tx_bytes: int = 0
    points: deque[tuple[float, float, float]] = field(
        default_factory=lambda: deque(maxlen=7200)
    )  # (Zeit, rx/s, tx/s)


def _absolute(value: float, watch: float, attack: float) -> int:
    if value >= attack:
        return 3
    if value >= watch:
        return 2
    return 1


def _delta(now: dict[str, int], before: dict[str, int], key: str) -> int:
    if key in now and key in before:
        return now[key] - before[key]
    return 0


class Detector:
    def __init__(self) -> None:
        self._states: dict[str, _State] = {}
        # Points loaded from the DB, until the first real frame arrives after the start.
        self._seed: dict[str, list[tuple[float, float, float]]] = {}

    def forget(self, name: str) -> None:
        self._states.pop(name, None)

    def snapshot(self, name: str, now: float) -> dict[str, Any] | None:
        state = self._states.get(name)
        if state is None:
            return None
        return {
            "level": state.level,
            "reasons": list(state.reasons),
            "samples": state.samples,
            "rates": dict(state.rates),
            "age": now - state.at,
        }

    def export_buckets(
        self, now_mono: float, now_wall: float, after: int
    ) -> list[tuple[str, int, int, int]]:
        """Abgeschlossene Buckets (Name, Start in Unix-Sekunden, rx, tx), neuer als `after`."""
        out: dict[tuple[str, int], tuple[int, int]] = {}
        for name, state in self._states.items():
            for at, rx_rate, tx_rate in state.points:
                wall = now_wall - (now_mono - at)
                bucket = int(wall // BUCKET_SECONDS) * BUCKET_SECONDS
                if bucket <= after or bucket + BUCKET_SECONDS > now_wall:
                    continue
                old_rx, old_tx = out.get((name, bucket), (0, 0))
                out[(name, bucket)] = (max(old_rx, round(rx_rate)), max(old_tx, round(tx_rate)))
        return [(name, bucket, rx, tx) for (name, bucket), (rx, tx) in out.items()]

    def restore(
        self, rows: list[tuple[str, int, int, int]], now_mono: float, now_wall: float
    ) -> None:
        """Takes over stored buckets. Wall clock time is converted to the monotonic clock."""
        for name, bucket, rx, tx in sorted(rows, key=lambda row: row[1]):
            at = now_mono - (now_wall - (bucket + BUCKET_SECONDS / 2))
            self._seed.setdefault(name, []).append((at, float(rx), float(tx)))

    def history(self, name: str, now: float) -> tuple[list[int], list[int]]:
        """rx/tx of the last hour in buckets, oldest first. Gaps are 0."""
        count = HISTORY_SECONDS // BUCKET_SECONDS
        rx, tx = [0] * count, [0] * count
        state = self._states.get(name)
        points = list(self._seed.get(name, ()))
        if state is not None:
            points.extend(state.points)
        for at, rx_rate, tx_rate in points:
            age = now - at
            if 0 <= age < HISTORY_SECONDS:
                i = count - 1 - int(age // BUCKET_SECONDS)
                rx[i] = max(rx[i], round(rx_rate))
                tx[i] = max(tx[i], round(tx_rate))
        return rx, tx

    def observe(
        self,
        name: str,
        now: float,
        rx_bytes: int,
        net: dict[str, int] | None = None,
        console: dict[str, int] | None = None,
        tx_bytes: int | None = None,
    ) -> Verdict:
        net = net or {}
        state = self._states.get(name)
        if state is None:
            state = _State(at=now, rx_bytes=rx_bytes, counters=dict(net), tx_bytes=tx_bytes or 0)
            self._states[name] = state
            seeded = self._seed.pop(name, None)
            if seeded:
                state.points.extend(seeded)
                # Baseline from the stored hour, so nothing has to be learned again.
                for _, rx_rate, _ in seeded:
                    state.bytes.history.append(rx_rate)
            return Verdict("learning", (), False)
        dt = now - state.at
        if dt < MIN_INTERVAL:
            return Verdict(state.level, state.reasons, False)

        before, previous_rx, previous_tx = state.counters, state.rx_bytes, state.tx_bytes
        state.at, state.rx_bytes, state.counters = now, rx_bytes, dict(net)
        if tx_bytes is not None:
            state.tx_bytes = tx_bytes
        # A counter that gets smaller means: the container was restarted.
        if (
            rx_bytes < previous_rx
            or (tx_bytes is not None and tx_bytes < previous_tx)
            or any(value < before[key] for key, value in net.items() if key in before)
        ):
            return Verdict(state.level, state.reasons, False)

        state.samples += 1
        found: list[tuple[int, str]] = []

        rx_rate = (rx_bytes - previous_rx) / dt
        tx_rate = (tx_bytes - previous_tx) / dt if tx_bytes is not None else 0.0
        state.points.append((now, rx_rate, tx_rate))
        while state.points and now - state.points[0][0] > HISTORY_SECONDS:
            state.points.popleft()
        bytes_index, usual, factor = state.bytes.add(rx_rate, BYTES_WATCH, BYTES_ATTACK)
        pps: float | None = None
        packets_index = 1
        if "rx_packets" in net and "rx_packets" in before:
            pps = (net["rx_packets"] - before["rx_packets"]) / dt
            packets_index, _, packets_factor = state.packets.add(pps, PPS_WATCH, PPS_ATTACK)
            if packets_index >= 2:
                found.append(
                    (packets_index, f"Incoming packet rate is {packets_factor:.0f}x the usual rate")
                )

        dropped = sum(_delta(net, before, key) for key in DROP_KEYS) / dt
        dropped_index = _absolute(dropped, DROP_WATCH, DROP_ATTACK)
        if dropped_index >= 2:
            found.append((dropped_index, f"{dropped:.0f} packets/s are dropped or rejected"))

        lines_rate: float | None = None
        sources_rate: float | None = None
        console_index = 1
        if console is not None and "window_lines" in console:
            lines_rate = console["window_lines"] / dt
            sources_rate = console.get("sources", 0) / dt
            console_index = _absolute(lines_rate, LINES_WATCH, LINES_ATTACK)
            if lines_rate >= SOURCES_MIN_LINES:
                console_index = max(
                    console_index, _absolute(sources_rate, SOURCES_WATCH, SOURCES_ATTACK)
                )
            if console_index >= 2:
                found.append(
                    (
                        console_index,
                        f"Console flooded with {lines_rate:.0f} lines/s "
                        f"from about {sources_rate:.0f} sources/s",
                    )
                )

        # Volume alone can be a legitimate download (e.g. Steam Workshop on an idle
        # server). "attack" needs a second signal: packets, drops or a console flood.
        if bytes_index >= 3 and max(packets_index, dropped_index, console_index) < 2:
            bytes_index = 2
        if bytes_index >= 2:
            found.append((bytes_index, f"Incoming traffic is {factor:.0f}x the usual rate"))

        index = max(1, bytes_index, packets_index, dropped_index, console_index)
        if index < 2 and bytes_index == 0:
            index = 0
        level = LEVELS[index]
        alert = level == "attack" and state.level != "attack"
        state.level = level
        state.reasons = tuple(text for _, text in sorted(found, key=lambda f: -f[0]))
        state.rates = {
            "rx_bytes_per_s": rx_rate,
            "rx_packets_per_s": pps,
            "dropped_per_s": dropped,
            "console_lines_per_s": lines_rate,
            "console_sources_per_s": sources_rate,
            "usual_rx_bytes_per_s": usual,
            "tx_bytes_per_s": tx_rate,
        }
        return Verdict(level, state.reasons, alert)


detector = Detector()
