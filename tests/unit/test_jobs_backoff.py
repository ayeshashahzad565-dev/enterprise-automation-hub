"""Unit tests for ``app.jobs.backoff.compute_delay_seconds``."""

from __future__ import annotations

import random

import pytest

from app.jobs.backoff import compute_delay_seconds

pytestmark = pytest.mark.unit


class TestComputeDelaySeconds:
    def test_delay_is_within_the_full_jitter_range_for_the_given_attempt(self):
        rand = random.Random(1234)

        delay = compute_delay_seconds(
            2, base_seconds=10.0, multiplier=2.0, cap_seconds=3600.0, rand=rand
        )

        # ceiling = min(3600, 10 * 2**2) = 40
        assert 0 <= delay <= 40

    def test_delay_is_deterministic_for_a_seeded_random_source(self):
        first = compute_delay_seconds(1, base_seconds=10.0, rand=random.Random(42))
        second = compute_delay_seconds(1, base_seconds=10.0, rand=random.Random(42))

        assert first == second

    def test_delay_is_capped_regardless_of_how_many_attempts_have_occurred(self):
        rand = random.Random(1)

        delay = compute_delay_seconds(
            50, base_seconds=30.0, multiplier=2.0, cap_seconds=100.0, rand=rand
        )

        assert 0 <= delay <= 100

    def test_delay_grows_with_more_attempts_on_average(self):
        rand = random.Random(7)
        small_ceiling_samples = [
            compute_delay_seconds(0, base_seconds=1.0, multiplier=2.0, cap_seconds=3600.0, rand=rand)
            for _ in range(200)
        ]
        large_ceiling_samples = [
            compute_delay_seconds(5, base_seconds=1.0, multiplier=2.0, cap_seconds=3600.0, rand=rand)
            for _ in range(200)
        ]

        assert sum(large_ceiling_samples) > sum(small_ceiling_samples)

    def test_zero_attempts_uses_the_base_delay_as_the_ceiling(self):
        rand = random.Random(3)

        delay = compute_delay_seconds(0, base_seconds=30.0, multiplier=2.0, rand=rand)

        assert 0 <= delay <= 30
