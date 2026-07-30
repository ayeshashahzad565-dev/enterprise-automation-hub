"""Unit tests for ``app.utils.rate_limiter.InMemoryRateLimiter``
(Milestone 9 hardening — the first enforced rate limit in this codebase).
"""

from __future__ import annotations

import threading

import pytest

from app.utils.rate_limiter import InMemoryRateLimiter, RateLimitExceededError

pytestmark = pytest.mark.unit


class TestInMemoryRateLimiter:
    def test_allows_requests_up_to_the_configured_limit(self):
        limiter = InMemoryRateLimiter(limit=3, window_seconds=60)

        limiter.check("1.2.3.4")
        limiter.check("1.2.3.4")
        limiter.check("1.2.3.4")

    def test_rejects_the_request_that_exceeds_the_limit(self):
        limiter = InMemoryRateLimiter(limit=2, window_seconds=60)
        limiter.check("1.2.3.4")
        limiter.check("1.2.3.4")

        with pytest.raises(RateLimitExceededError):
            limiter.check("1.2.3.4")

    def test_a_limit_of_zero_blocks_every_request(self):
        limiter = InMemoryRateLimiter(limit=0, window_seconds=60)

        with pytest.raises(RateLimitExceededError):
            limiter.check("1.2.3.4")

    def test_different_keys_have_independent_budgets(self):
        limiter = InMemoryRateLimiter(limit=1, window_seconds=60)
        limiter.check("1.2.3.4")

        # A different caller (key) is not affected by the first one's usage.
        limiter.check("5.6.7.8")

        with pytest.raises(RateLimitExceededError):
            limiter.check("1.2.3.4")

    def test_hits_outside_the_window_are_evicted_and_no_longer_count(self, monkeypatch):
        current_time = [1000.0]
        monkeypatch.setattr("app.utils.rate_limiter.time.monotonic", lambda: current_time[0])
        limiter = InMemoryRateLimiter(limit=1, window_seconds=10)
        limiter.check("1.2.3.4")
        with pytest.raises(RateLimitExceededError):
            limiter.check("1.2.3.4")

        current_time[0] += 10.001

        # The old hit has aged out of the window - this succeeds.
        limiter.check("1.2.3.4")

    def test_retry_after_reflects_the_remaining_window(self, monkeypatch):
        current_time = [1000.0]
        monkeypatch.setattr("app.utils.rate_limiter.time.monotonic", lambda: current_time[0])
        limiter = InMemoryRateLimiter(limit=1, window_seconds=10)
        limiter.check("1.2.3.4")

        current_time[0] += 4.0
        with pytest.raises(RateLimitExceededError) as exc_info:
            limiter.check("1.2.3.4")

        # 10s window, 4s elapsed -> ~6s remaining.
        assert 5.0 <= exc_info.value.retry_after_seconds <= 6.0

    def test_retry_after_is_never_reported_below_one_second(self, monkeypatch):
        current_time = [1000.0]
        monkeypatch.setattr("app.utils.rate_limiter.time.monotonic", lambda: current_time[0])
        limiter = InMemoryRateLimiter(limit=1, window_seconds=10)
        limiter.check("1.2.3.4")

        current_time[0] += 9.999
        with pytest.raises(RateLimitExceededError) as exc_info:
            limiter.check("1.2.3.4")

        assert exc_info.value.retry_after_seconds >= 1.0

    def test_is_thread_safe_under_concurrent_checks(self):
        limiter = InMemoryRateLimiter(limit=50, window_seconds=60)
        rejected = 0
        rejected_lock = threading.Lock()

        def _hit():
            nonlocal rejected
            try:
                limiter.check("shared-key")
            except RateLimitExceededError:
                with rejected_lock:
                    rejected += 1

        threads = [threading.Thread(target=_hit) for _ in range(80)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly 30 of the 80 concurrent hits must have been rejected -
        # a race in the counter would allow more than 50 through, or
        # reject more than necessary due to lost updates.
        assert rejected == 30
