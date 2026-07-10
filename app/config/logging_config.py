"""Structured logging configuration.

Per the ADD's logging philosophy and API-ADD Section 27's Observability
requirements, EAH uses Python's standard ``logging`` module exclusively —
no external logging framework or agent is introduced. This module
configures that standard logging so that every log entry, across every
layer of the application, is emitted in a consistent, structured shape:
``timestamp``, ``level``, ``logger``, ``message``, plus whatever
request-scoped context (``request_id``, ``user_id``, ``component``,
``outcome``, ``duration_ms``) the emitting code attaches via the standard
``extra=`` argument to a logging call.

This module deliberately has no dependency on ``settings.py`` — it accepts
a plain log-level string, so that logging can be configured as the very
first step of application startup, before the rest of configuration has
necessarily finished loading, and so that it remains trivially callable
from a test's own setup without constructing a full ``AppSettings``
instance.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Final

from app.config.constants import DEFAULT_LOG_LEVEL, VALID_LOG_LEVELS
from app.config.exceptions import LoggingConfigurationError

#: The record attributes considered "standard" ``logging.LogRecord``
#: attributes, used by ``StructuredFormatter`` to distinguish
#: caller-supplied ``extra=`` fields (which should be surfaced in the
#: structured output) from the record's own built-in bookkeeping
#: attributes (which should not be duplicated into the output).
_STANDARD_RECORD_ATTRIBUTES: Final[frozenset[str]] = frozenset(
    logging.LogRecord(
        name="", level=0, pathname="", lineno=0, msg="", args=(), exc_info=None
    ).__dict__.keys()
)


class StructuredFormatter(logging.Formatter):
    """A ``logging.Formatter`` that emits each record as a single-line JSON object.

    Every emitted line always includes ``timestamp`` (UTC, ISO-8601),
    ``level``, ``logger``, and ``message``. Any additional field passed
    via a logging call's ``extra=`` argument (for example,
    ``logger.info("...", extra={"request_id": ..., "duration_ms": ...})``)
    is included as-is, and any field not supplied on a given record is
    simply absent from that record's output — this formatter never
    fabricates a placeholder value for a field the caller did not
    provide, per API-ADD Section 27's description of these fields as
    populated "where applicable."
    """

    def format(self, record: logging.LogRecord) -> str:
        """Render a log record as a single-line JSON string.

        Args:
            record: The log record to format.

        Returns:
            A JSON-encoded string representing the record's structured
            fields.
        """
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for key, value in record.__dict__.items():
            if key in _STANDARD_RECORD_ATTRIBUTES:
                continue
            payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def configure_logging(level: str = DEFAULT_LOG_LEVEL) -> None:
    """Configure the root logger with EAH's structured logging format.

    Per DG Section 14.3, output is written to stdout, where the hosting
    platform's own native log aggregation is expected to collect it — no
    additional logging service or agent is configured by this function.

    Calling this function replaces any handlers already attached to the
    root logger, so it is safe to call more than once (for example, once
    in production startup and again at the start of each test module)
    without producing duplicated log lines.

    Args:
        level: The minimum log level to emit, as a standard logging level
            name (one of ``VALID_LOG_LEVELS``). Defaults to
            ``DEFAULT_LOG_LEVEL`` ("INFO").

    Raises:
        LoggingConfigurationError: If ``level`` is not a recognized
            logging level name.
    """
    normalized_level = level.strip().upper()
    if normalized_level not in VALID_LOG_LEVELS:
        raise LoggingConfigurationError(
            f"Invalid log level {level!r}. Expected one of: "
            f"{sorted(VALID_LOG_LEVELS)}."
        )

    root_logger = logging.getLogger()
    for existing_handler in list(root_logger.handlers):
        root_logger.removeHandler(existing_handler)

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(StructuredFormatter())

    root_logger.addHandler(handler)
    root_logger.setLevel(normalized_level)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger, configured per ``configure_logging``'s setup.

    A thin convenience wrapper over ``logging.getLogger`` so that calling
    code obtains its logger through the same module that owns logging
    configuration, rather than importing the standard ``logging`` module
    directly at every call site.

    Args:
        name: The logger's name, conventionally ``__name__`` of the
            calling module.

    Returns:
        The named ``logging.Logger`` instance.
    """
    return logging.getLogger(name)