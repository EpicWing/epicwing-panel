import time
from collections import defaultdict, deque
from threading import Lock


class FailureLimiter:
    """Zählt Fehlversuche pro Schlüssel in einem gleitenden Zeitfenster (nur im Speicher)."""

    def __init__(self, max_failures: int, window_seconds: int) -> None:
        self.max_failures = max_failures
        self.window = window_seconds
        self._failures: defaultdict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def retry_after(self, key: str) -> int:
        """Sekunden bis zum nächsten erlaubten Versuch, 0 wenn erlaubt."""
        now = time.monotonic()
        with self._lock:
            attempts = self._failures.get(key)
            if not attempts:
                return 0
            self._expire(attempts, now)
            if not attempts:
                del self._failures[key]
                return 0
            if len(attempts) >= self.max_failures:
                return int(self.window - (now - attempts[0])) + 1
            return 0

    def add_failure(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            if len(self._failures) > 10_000:
                self._sweep(now)
            self._failures[key].append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._failures.clear()

    def _expire(self, attempts: deque[float], now: float) -> None:
        while attempts and now - attempts[0] > self.window:
            attempts.popleft()

    def _sweep(self, now: float) -> None:
        for key in list(self._failures):
            attempts = self._failures[key]
            self._expire(attempts, now)
            if not attempts:
                del self._failures[key]


login_ip_limiter = FailureLimiter(max_failures=20, window_seconds=900)
login_email_limiter = FailureLimiter(max_failures=5, window_seconds=900)
password_change_limiter = FailureLimiter(max_failures=5, window_seconds=900)
enroll_limiter = FailureLimiter(max_failures=10, window_seconds=900)
agent_auth_limiter = FailureLimiter(max_failures=10, window_seconds=900)
