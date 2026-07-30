"""Full-jitter exponential backoff for job retries.

A pure function with no Redis/Postgres dependency of its own, deliberately
separated out so it is trivially unit-testable in isolation
(``tests/unit/test_jobs_backoff.py``) with a seeded ``random`` instance.

Full jitter (picking a delay uniformly between zero and the deterministic
exponential ceiling) is used rather than the exponential delay directly,
because it is the simplest scheme that also prevents many jobs retrying
in lockstep from synchronizing into a retry storm — a well-established
tradeoff (see AWS's "Exponential Backoff and Jitter" architecture blog
post), and a "revisit only if this proves insufficient" default rather
than a more elaborate decorrelated-jitter scheme this codebase has no
evidence it needs yet.
"""

from __future__ import annotations

import random

__all__ = ["DEFAULT_BASE_SECONDS", "DEFAULT_MULTIPLIER", "DEFAULT_CAP_SECONDS", "compute_delay_seconds"]

#: The delay before the first retry (attempt 0 -> attempt 1), before
#: jitter is applied.
DEFAULT_BASE_SECONDS = 30.0
#: How quickly the ceiling grows per additional attempt.
DEFAULT_MULTIPLIER = 2.0
#: The ceiling never exceeds this, regardless of how many attempts have
#: already been made — an hour is long enough to ride out a typical
#: transient outage (an SMTP provider blip, a brief network partition)
#: without letting a single job's retry schedule drift so far into the
#: future that an operator inspecting "why hasn't this retried yet" is
#: surprised by the answer.
DEFAULT_CAP_SECONDS = 3600.0


def compute_delay_seconds(
    attempts: int,
    *,
    base_seconds: float = DEFAULT_BASE_SECONDS,
    multiplier: float = DEFAULT_MULTIPLIER,
    cap_seconds: float = DEFAULT_CAP_SECONDS,
    rand: random.Random | None = None,
) -> float:
    """Compute how long to wait before the next retry attempt.

    Args:
        attempts: The number of attempts already made (the failure that
            just occurred counts as one) — ``1`` after a job's first
            attempt failed.
        base_seconds: The delay ceiling before the first retry.
        multiplier: How quickly the ceiling grows per additional attempt.
        cap_seconds: The absolute ceiling, regardless of ``attempts``.
        rand: The random source to draw jitter from. Defaults to the
            module-level ``random`` functions; tests pass a seeded
            ``random.Random`` instance for determinism.

    Returns:
        A delay in seconds, uniformly distributed between ``0`` and
        ``min(cap_seconds, base_seconds * multiplier ** attempts)``.
    """
    ceiling = min(cap_seconds, base_seconds * (multiplier**attempts))
    source = rand if rand is not None else random
    return source.uniform(0, ceiling)
