"""Tests for the rate limiter."""

import sys
import os
import time
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.rate_limiter import TokenBucket, DomainRateLimiter


class TestTokenBucket:
    """Tests for the TokenBucket class."""

    def test_initial_capacity(self):
        bucket = TokenBucket(rate=10.0, capacity=5)
        assert bucket.available_tokens >= 4.9  # Allow small timing drift

    def test_acquire_returns_true(self):
        bucket = TokenBucket(rate=10.0, capacity=5)
        assert bucket.acquire(timeout=1.0) is True

    def test_acquire_depletes_tokens(self):
        bucket = TokenBucket(rate=1.0, capacity=2)
        bucket.acquire(timeout=1.0)
        bucket.acquire(timeout=1.0)
        # After 2 acquires with capacity 2, should be near 0
        assert bucket.available_tokens < 1.0

    def test_tokens_refill_over_time(self):
        bucket = TokenBucket(rate=100.0, capacity=10)
        # Drain all tokens
        for _ in range(10):
            bucket.acquire(timeout=1.0)
        # Wait for refill
        time.sleep(0.15)
        assert bucket.available_tokens >= 1.0

    def test_acquire_timeout_returns_false(self):
        bucket = TokenBucket(rate=0.1, capacity=1)
        bucket.acquire(timeout=1.0)  # Drain the single token
        # With very slow rate (0.1/s), 0.1s timeout should fail
        result = bucket.acquire(timeout=0.1)
        assert result is False

    def test_capacity_is_max(self):
        bucket = TokenBucket(rate=1000.0, capacity=5)
        time.sleep(0.1)
        # Even after time passes, tokens shouldn't exceed capacity
        assert bucket.available_tokens <= 5.0


class TestDomainRateLimiter:
    """Tests for the DomainRateLimiter class."""

    def test_acquire_succeeds(self):
        limiter = DomainRateLimiter(
            global_rate=100.0, global_capacity=100,
            domain_rate=100.0, domain_capacity=100,
        )
        assert limiter.acquire("https://example.com/page") is True

    def test_separate_domain_buckets(self):
        limiter = DomainRateLimiter(
            global_rate=100.0, global_capacity=100,
            domain_rate=100.0, domain_capacity=100,
        )
        limiter.acquire("https://a.com/page1")
        limiter.acquire("https://b.com/page1")
        status = limiter.get_status()
        assert "a.com" in status["domains"]
        assert "b.com" in status["domains"]

    def test_get_status(self):
        limiter = DomainRateLimiter()
        status = limiter.get_status()
        assert "global_rate" in status
        assert "domain_rate" in status
        assert "domains" in status

    def test_thread_safety(self):
        """Multiple threads should be able to acquire without errors."""
        limiter = DomainRateLimiter(
            global_rate=1000.0, global_capacity=100,
            domain_rate=1000.0, domain_capacity=100,
        )
        errors = []

        def worker():
            try:
                for i in range(10):
                    limiter.acquire(f"https://example.com/page{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
