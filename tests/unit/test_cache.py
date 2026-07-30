"""Tests for ``app.utils.cache.TTLCache``/``cached_method`` (Milestone 13,
Medium finding 9).
"""

from __future__ import annotations

import threading
import time

import pytest

from app.utils.cache import TTLCache, cached_method

pytestmark = pytest.mark.unit


class TestTTLCache:
    def test_a_second_call_within_the_ttl_returns_the_cached_value(self):
        cache = TTLCache(ttl_seconds=60.0)
        calls = []

        def compute():
            calls.append(1)
            return "value"

        first = cache.get_or_compute("key", compute)
        second = cache.get_or_compute("key", compute)

        assert first == "value"
        assert second == "value"
        assert len(calls) == 1

    def test_different_keys_are_computed_independently(self):
        cache = TTLCache(ttl_seconds=60.0)

        a = cache.get_or_compute("a", lambda: "A")
        b = cache.get_or_compute("b", lambda: "B")

        assert a == "A"
        assert b == "B"

    def test_a_call_after_the_ttl_expires_recomputes(self):
        cache = TTLCache(ttl_seconds=0.05)
        calls = []

        def compute():
            calls.append(1)
            return len(calls)

        first = cache.get_or_compute("key", compute)
        time.sleep(0.1)
        second = cache.get_or_compute("key", compute)

        assert first == 1
        assert second == 2

    def test_a_zero_ttl_disables_caching_entirely(self):
        cache = TTLCache(ttl_seconds=0.0)
        calls = []

        def compute():
            calls.append(1)
            return len(calls)

        first = cache.get_or_compute("key", compute)
        second = cache.get_or_compute("key", compute)

        assert first == 1
        assert second == 2

    def test_concurrent_misses_on_the_same_key_compute_only_once(self):
        """A cache stampede: several threads racing a cold cache for the
        *same* key previously each called ``compute`` independently. Only
        the first should actually compute; the rest must wait for it and
        then read its result, rather than redundantly recomputing (e.g.
        opening the Analytics page's Intelligence tab, whose several
        cards all resolve through the same expensive underlying call)."""
        cache = TTLCache(ttl_seconds=60.0)
        started = threading.Event()
        release = threading.Event()
        call_count = 0
        lock = threading.Lock()

        def compute():
            nonlocal call_count
            with lock:
                call_count += 1
            started.set()
            release.wait(timeout=5)
            return "value"

        first_thread = threading.Thread(target=lambda: cache.get_or_compute("key", compute))
        first_thread.start()
        assert started.wait(timeout=5), "compute() was never entered"

        results = []
        other_threads = [
            threading.Thread(
                target=lambda: results.append(cache.get_or_compute("key", compute))
            )
            for _ in range(5)
        ]
        for t in other_threads:
            t.start()
        time.sleep(0.05)  # give the other threads a chance to reach get_or_compute and block

        release.set()
        first_thread.join(timeout=5)
        for t in other_threads:
            t.join(timeout=5)

        assert call_count == 1
        assert results == ["value"] * 5

    def test_an_exception_from_compute_is_never_cached(self):
        cache = TTLCache(ttl_seconds=60.0)
        calls = []

        def compute():
            calls.append(1)
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            cache.get_or_compute("key", compute)
        with pytest.raises(ValueError, match="boom"):
            cache.get_or_compute("key", compute)

        assert len(calls) == 2


class _Widget:
    def __init__(self, *, cache_ttl_seconds: float) -> None:
        self._response_cache = TTLCache(ttl_seconds=cache_ttl_seconds)
        self.calls = 0

    @cached_method
    def compute(self, *, value: int, unhashable: list | None = None) -> int:
        self.calls += 1
        return value * 2


class TestCachedMethod:
    def test_repeated_calls_with_the_same_arguments_hit_the_cache(self):
        widget = _Widget(cache_ttl_seconds=60.0)

        first = widget.compute(value=5)
        second = widget.compute(value=5)

        assert first == second == 10
        assert widget.calls == 1

    def test_calls_with_different_arguments_are_not_conflated(self):
        widget = _Widget(cache_ttl_seconds=60.0)

        widget.compute(value=5)
        widget.compute(value=6)

        assert widget.calls == 2

    def test_disabled_by_default_ttl_zero_recomputes_every_call(self):
        widget = _Widget(cache_ttl_seconds=0.0)

        widget.compute(value=5)
        widget.compute(value=5)

        assert widget.calls == 2

    def test_an_unhashable_argument_bypasses_the_cache_without_raising(self):
        widget = _Widget(cache_ttl_seconds=60.0)

        result = widget.compute(value=5, unhashable=[1, 2, 3])

        assert result == 10
        assert widget.calls == 1
