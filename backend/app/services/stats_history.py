"""Letzte Messwerte pro Server im Speicher, damit neue Browser-Tabs volle Graphen sehen."""

import time
from collections import deque
from typing import Any

# Der Agent misst alle 2 s, die Graphen zeigen 60 Punkte (eine Rate braucht zwei Messungen).
HISTORY_SAMPLES = 61
KEYS = (
    "cpu_percent",
    "memory_used_bytes",
    "disk_used_bytes",
    "network_rx_bytes",
    "network_tx_bytes",
)

_samples: dict[str, deque[dict[str, Any]]] = {}


def record(name: str, payload: dict[str, Any]) -> None:
    buffer = _samples.setdefault(name, deque(maxlen=HISTORY_SAMPLES))
    buffer.append({"t": int(time.time() * 1000), **{key: payload[key] for key in KEYS}})


def snapshot(name: str) -> list[dict[str, Any]]:
    return list(_samples.get(name, ()))


def clear(name: str) -> None:
    _samples.pop(name, None)
