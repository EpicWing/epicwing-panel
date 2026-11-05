import time
from collections import defaultdict, deque
from threading import Lock


class FailureLimiter:
    """Counts failed attempts per key in a sliding time window (memory only)."""

    def __init__(self, max_failures: int, window_seconds: int) -> None:
        self.max_failures = max_failures
        self.window = window_seconds
        self._failures: defaultdict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def retry_after(self, key: str) -> int:
        """Seconds until the next allowed attempt, 0 if allowed."""
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

    def reset_suffix(self, suffix: str) -> None:
        """Löscht alle Schlüssel, die auf suffix enden (z. B. alle IPs einer E-Mail)."""
        with self._lock:
            for key in [k for k in self._failures if k.endswith(suffix)]:
                del self._failures[key]

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
sftp_reject_limiter = FailureLimiter(max_failures=10, window_seconds=900)
enroll_limiter = FailureLimiter(max_failures=10, window_seconds=900)
agent_auth_limiter = FailureLimiter(max_failures=10, window_seconds=900)
totp_limiter = FailureLimiter(max_failures=5, window_seconds=900)
reset_request_ip_limiter = FailureLimiter(max_failures=10, window_seconds=900)
reset_request_email_limiter = FailureLimiter(max_failures=3, window_seconds=900)
reset_confirm_ip_limiter = FailureLimiter(max_failures=10, window_seconds=900)
