"""
Rate Limiter — Token-bucket algorithm implemented with stdlib threading.

Provides both per-domain and global rate limiting so the crawler
can respect target servers while controlling overall throughput.
"""

import time
import threading
from urllib.parse import urlparse


class TokenBucket:
    """
    Classic token-bucket rate limiter.

    Tokens refill at `rate` tokens per second, up to `capacity`.
    Calling acquire() blocks until a token is available.
    """

    def __init__(self, rate: float, capacity: int) -> None:
        self.rate = rate            # tokens per second
        self.capacity = capacity    # max burst size
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, timeout: float | None = None) -> bool:
        """
        Block until a token is available. Returns True if acquired,
        False if timeout expired.
        """
        deadline = None if timeout is None else time.monotonic() + timeout

        while True:
            with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return True

            # Sleep a short interval then retry
            if deadline is not None and time.monotonic() >= deadline:
                return False
            time.sleep(min(0.05, 1.0 / max(self.rate, 1)))

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        self._last_refill = now

    @property
    def available_tokens(self) -> float:
        with self._lock:
            self._refill()
            return self._tokens


class DomainRateLimiter:
    """
    Manages per-domain and global rate limiting.

    - Global bucket: limits total requests/s across all domains
    - Per-domain buckets: limits requests/s to each individual domain
    """

    def __init__(
        self,
        global_rate: float = 10.0,
        global_capacity: int = 20,
        domain_rate: float = 2.0,
        domain_capacity: int = 5,
    ) -> None:
        self.global_rate = global_rate
        self.domain_rate = domain_rate
        self.domain_capacity = domain_capacity

        self._global_bucket = TokenBucket(global_rate, global_capacity)
        self._domain_buckets: dict[str, TokenBucket] = {}
        self._lock = threading.Lock()

    def acquire(self, url: str, timeout: float = 30.0) -> bool:
        """
        Acquire rate-limit tokens for the given URL.
        Blocks until both global and per-domain tokens are available.
        """
        domain = urlparse(url).netloc.lower()

        # Get or create domain bucket
        with self._lock:
            if domain not in self._domain_buckets:
                self._domain_buckets[domain] = TokenBucket(
                    self.domain_rate, self.domain_capacity
                )
            domain_bucket = self._domain_buckets[domain]

        # Acquire global token first, then domain token
        if not self._global_bucket.acquire(timeout=timeout):
            return False
        if not domain_bucket.acquire(timeout=timeout):
            return False
        return True

    def get_status(self) -> dict:
        """Return current rate limiter status for monitoring."""
        with self._lock:
            domain_statuses = {
                domain: {
                    "available_tokens": round(bucket.available_tokens, 1),
                    "rate": bucket.rate,
                }
                for domain, bucket in self._domain_buckets.items()
            }

        return {
            "global_available_tokens": round(self._global_bucket.available_tokens, 1),
            "global_rate": self.global_rate,
            "domain_rate": self.domain_rate,
            "domains": domain_statuses,
        }
