"""Configurable, bounded retry utilities for transient failures.

Per the Architecture Design Document's Error Handling Strategy: "Transient
failures (timeouts) are retried a bounded number of times at the
repository boundary; persistent failures propagate as RepositoryError."
This module provides the generic retry mechanism that statement
describes — configurable, bounded, and exponential-backoff-based — as a
reusable primitive independent of any specific repository or failure
type, so that the Repository Layer (and any other layer that needs
bounded retry behavior for a transient failure) applies this mechanism
rather than re-implementing its own retry loop.

This module never retries unconditionally or unboundedly: every retry
policy has a fixed maximum attempt count, and only exception types the
caller explicitly designates as retryable trigger a retry at all — every
other exception propagates immediately on its first occurrence.
"""

from __future__ import annotations

import functools
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Callable, ParamSpec, TypeVar

from app.utils.exceptions import RetryExhaustedError

__all__ = ["RetryPolicy", "retry_call", "retry"]

P = ParamSpec("P")
R = TypeVar("R")

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """A configurable, bounded retry policy.

    Attributes:
        max_attempts: The maximum number of attempts, including the
            first (non-retry) attempt. Must be at least 1.
        base_delay_seconds: The delay before the first retry.
        backoff_multiplier: The factor the delay is multiplied by after
            each subsequent retry (exponential backoff). A value of
            ``1.0`` produces a constant delay between retries.
        max_delay_seconds: An upper bound on the delay between any two
            attempts, preventing unbounded growth from the exponential
            backoff.
        jitter: Whether to add random jitter (up to 25% of the computed
            delay) to each retry's delay, reducing the likelihood of
            multiple retrying callers synchronizing their retry attempts
            against a recovering dependency.
        retryable_exceptions: The exception types that trigger a retry.
            Any exception not an instance of one of these types
            propagates immediately, without consuming a retry attempt.
    """

    max_attempts: int = 3
    base_delay_seconds: float = 0.5
    backoff_multiplier: float = 2.0
    max_delay_seconds: float = 10.0
    jitter: bool = True
    retryable_exceptions: tuple[type[BaseException], ...] = field(
        default_factory=lambda: (Exception,)
    )

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError(f"max_attempts must be >= 1, got {self.max_attempts}.")
        if self.base_delay_seconds < 0:
            raise ValueError("base_delay_seconds must be >= 0.")
        if self.backoff_multiplier < 1:
            raise ValueError("backoff_multiplier must be >= 1.")
        if self.max_delay_seconds < self.base_delay_seconds:
            raise ValueError("max_delay_seconds must be >= base_delay_seconds.")

    def delay_for_attempt(self, attempt_number: int) -> float:
        """Compute the delay to wait before a given retry attempt.

        Args:
            attempt_number: The 1-indexed retry attempt number (``1`` for
                the first retry, i.e. the second overall attempt).

        Returns:
            The delay in seconds, bounded by ``max_delay_seconds`` and
            optionally jittered.
        """
        raw_delay = self.base_delay_seconds * (self.backoff_multiplier ** (attempt_number - 1))
        bounded_delay = min(raw_delay, self.max_delay_seconds)
        if not self.jitter:
            return bounded_delay
        return bounded_delay + random.uniform(0, bounded_delay * 0.25)


#: A conservative default policy: three total attempts, half-second base
#: delay, doubling backoff, ten-second cap, jitter enabled. Callers with
#: more specific requirements (e.g. a different retryable exception set)
#: should construct their own ``RetryPolicy`` rather than mutate this one,
#: since ``RetryPolicy`` is immutable by design.
DEFAULT_RETRY_POLICY = RetryPolicy()


def retry_call(func: Callable[[], R], *, policy: RetryPolicy = DEFAULT_RETRY_POLICY) -> R:
    """Invoke a zero-argument callable with bounded retry on failure.

    Args:
        func: The callable to invoke. Takes no arguments; callers with
            arguments to pass should wrap their target in a lambda or use
            ``functools.partial``, or prefer the ``retry`` decorator
            below for the common case of retrying an entire function
            definition.
        policy: The retry policy to apply. Defaults to
            ``DEFAULT_RETRY_POLICY``.

    Returns:
        The result of the first successful invocation.

    Raises:
        RetryExhaustedError: If every attempt, up to
            ``policy.max_attempts``, raises a retryable exception. The
            final attempt's exception is preserved as this exception's
            ``last_exception`` attribute and as its ``__cause__``.
        BaseException: Immediately, without retrying, if ``func`` raises
            an exception not matching ``policy.retryable_exceptions``.
    """
    last_exception: BaseException | None = None
    for attempt_number in range(1, policy.max_attempts + 1):
        try:
            return func()
        except policy.retryable_exceptions as exc:
            last_exception = exc
            if attempt_number == policy.max_attempts:
                break
            delay = policy.delay_for_attempt(attempt_number)
            logger.warning(
                "Attempt %d/%d failed, retrying in %.3fs: %s",
                attempt_number,
                policy.max_attempts,
                delay,
                exc,
                extra={
                    "component": "app.utils.retry",
                    "attempt": attempt_number,
                    "max_attempts": policy.max_attempts,
                },
            )
            time.sleep(delay)

    assert last_exception is not None  # noqa: S101 - loop always assigns before breaking
    raise RetryExhaustedError(policy.max_attempts, last_exception)


def retry(policy: RetryPolicy = DEFAULT_RETRY_POLICY) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator applying bounded retry behavior to a function.

    Args:
        policy: The retry policy to apply. Defaults to
            ``DEFAULT_RETRY_POLICY``.

    Returns:
        A decorator that wraps the target function with the retry
        behavior described in ``retry_call``.
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            return retry_call(lambda: func(*args, **kwargs), policy=policy)

        return wrapper

    return decorator