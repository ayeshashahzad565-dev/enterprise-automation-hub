"""Generic, reusable function decorators.

Per the ADD's logging philosophy and API-ADD Section 27's observability
requirements, this module provides cross-cutting decorators — call
logging, execution timing, and exception suppression — implemented once,
generically, so that any function anywhere in the codebase can opt into
this behavior by application rather than by hand-writing the same
``try``/``except``/``logging`` boilerplate at every call site.

Every decorator in this module is fully generic over its wrapped
function's signature (via ``ParamSpec``) and return type (via
``TypeVar``), so that type checkers see through the decorator to the
original function's actual signature.
"""

from __future__ import annotations

import functools
import logging
import time
import warnings
from collections.abc import Callable
from typing import ParamSpec, TypeVar

__all__ = ["log_calls", "timed", "suppress_and_log", "deprecated"]

P = ParamSpec("P")
R = TypeVar("R")

_DEFAULT_LOGGER_NAME = "app.utils.decorators"


def _resolve_logger(logger: logging.Logger | None, func: Callable[..., object]) -> logging.Logger:
    """Return the logger a decorator should use.

    Args:
        logger: An explicitly supplied logger, or ``None``.
        func: The function being decorated, used to derive a
            module-qualified default logger name when ``logger`` is not
            supplied.

    Returns:
        ``logger`` if supplied, otherwise a logger named after
        ``func``'s own module.
    """
    return logger if logger is not None else logging.getLogger(func.__module__)


def log_calls(
    logger: logging.Logger | None = None, *, level: int = logging.DEBUG
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator that logs a function's entry, successful exit, and any
    raised exception.

    Emits a structured log entry (per ``app.config.logging_config``'s
    ``StructuredFormatter``, which surfaces any ``extra=`` field
    automatically) on entry, on successful return, and on exception,
    including the function's fully qualified name in every entry via the
    ``component`` field.

    Args:
        logger: The logger to use. Defaults to a logger named after the
            decorated function's own module.
        level: The log level used for entry/exit messages. Exceptions are
            always logged at ``ERROR`` regardless of this setting.

    Returns:
        A decorator that wraps the target function with call logging.
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        resolved_logger = _resolve_logger(logger, func)
        component = func.__qualname__

        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            resolved_logger.log(
                level, "Calling %s", component, extra={"component": component, "outcome": "started"}
            )
            try:
                result = func(*args, **kwargs)
            except Exception as exc:
                resolved_logger.error(
                    "Exception in %s: %s",
                    component,
                    exc,
                    exc_info=exc,
                    extra={"component": component, "outcome": "failure"},
                )
                raise
            resolved_logger.log(
                level,
                "Completed %s",
                component,
                extra={"component": component, "outcome": "success"},
            )
            return result

        return wrapper

    return decorator


def timed(
    logger: logging.Logger | None = None, *, level: int = logging.INFO
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator that logs a function's execution duration.

    Emits a single structured log entry after the wrapped function
    returns (or raises), including a ``duration_ms`` field, matching the
    structured logging field the ADD and API-ADD both specify (API-ADD
    Section 27). Duration is measured with ``time.perf_counter`` for
    monotonic, high-resolution timing, independent of any wall-clock
    adjustment.

    Args:
        logger: The logger to use. Defaults to a logger named after the
            decorated function's own module.
        level: The log level used for the timing message.

    Returns:
        A decorator that wraps the target function with duration logging.
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        resolved_logger = _resolve_logger(logger, func)
        component = func.__qualname__

        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                duration_ms = round((time.perf_counter() - start) * 1000, 3)
                resolved_logger.log(
                    level,
                    "%s completed in %.3fms",
                    component,
                    duration_ms,
                    extra={"component": component, "duration_ms": duration_ms},
                )

        return wrapper

    return decorator


def suppress_and_log(
    *exception_types: type[BaseException],
    logger: logging.Logger | None = None,
    default: object = None,
) -> Callable[[Callable[P, R]], Callable[P, R | object]]:
    """Decorator that catches specified exception types, logs them, and
    returns a default value instead of propagating.

    Intended for genuinely optional, best-effort operations where the
    architecture documents specify that a failure must not interrupt the
    caller's own success path — for example, the ADD's description of
    email dispatch as an effect independent of a notification's in-app
    creation: a failure sending the email should be logged, not allowed
    to fail the surrounding operation. This decorator does not decide
    *which* operations qualify for this treatment; it is a generic
    mechanism a caller applies deliberately, only where the architecture
    already calls for this behavior.

    Args:
        *exception_types: One or more exception types to catch. If none
            are provided, ``Exception`` is caught by default.
        logger: The logger to use. Defaults to a logger named after the
            decorated function's own module.
        default: The value to return when a caught exception occurs.

    Returns:
        A decorator that wraps the target function with exception
        suppression and logging.
    """
    types_to_catch: tuple[type[BaseException], ...] = exception_types or (Exception,)

    def decorator(func: Callable[P, R]) -> Callable[P, R | object]:
        resolved_logger = _resolve_logger(logger, func)
        component = func.__qualname__

        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R | object:
            try:
                return func(*args, **kwargs)
            except types_to_catch as exc:
                resolved_logger.warning(
                    "Suppressed exception in %s: %s",
                    component,
                    exc,
                    exc_info=exc,
                    extra={"component": component, "outcome": "suppressed"},
                )
                return default

        return wrapper

    return decorator


def deprecated(reason: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator that marks a function as deprecated.

    Emits a ``DeprecationWarning`` on every call, following the same
    "deprecate, then remove after a sunset period" philosophy the API
    Design Document applies at the endpoint level (API-ADD Section 16),
    applied here at the level of an individual Python function.

    Args:
        reason: A short explanation of why the function is deprecated
            and, ideally, what to use instead.

    Returns:
        A decorator that wraps the target function with a deprecation
        warning.
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            warnings.warn(
                f"{func.__qualname__} is deprecated: {reason}",
                category=DeprecationWarning,
                stacklevel=2,
            )
            return func(*args, **kwargs)

        return wrapper

    return decorator
