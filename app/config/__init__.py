"""Configuration Layer for the Enterprise Automation Hub.

Per the Architecture Design Document, this package is the sole owner of
environment-variable access in the entire codebase — every other
package (``app.database``, ``app.models``, and every package yet to be
built) receives its configuration by dependency injection from the
``AppSettings`` instance this package constructs, rather than reading
``os.environ`` itself.

This package contains:

- ``exceptions``: the typed exception hierarchy every configuration
  failure raises.
- ``constants``: fixed, non-secret values — environment variable names
  and their defaults.
- ``environment``: the ``Environment`` enum and the logic that detects
  which one is currently running.
- ``security``: fixed security-relevant constants and secret-redaction
  helpers.
- ``paths``: filesystem path constants, derived purely from this file's
  own location in the project tree.
- ``logging_config``: structured logging setup, independent of the rest
  of this package's configuration loading.
- ``settings``: ``AppSettings`` and ``load_settings``, the Configuration
  Loader itself.

This module re-exports the public surface of every submodule so that
calling code can import from ``app.config`` directly.
"""

from __future__ import annotations

from app.config.constants import (
    API_VERSION_PREFIX,
    APP_NAME,
    APP_SHORT_NAME,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    VALID_LOG_LEVELS,
)
from app.config.environment import DEFAULT_ENVIRONMENT, Environment, detect_environment
from app.config.exceptions import (
    ConfigurationError,
    EnvironmentDetectionError,
    InvalidConfigurationValueError,
    LoggingConfigurationError,
    MissingEnvironmentVariableError,
)
from app.config.logging_config import StructuredFormatter, configure_logging, get_logger
from app.config.paths import (
    APP_DIR,
    CONFIG_PACKAGE_DIR,
    DATABASE_MIGRATIONS_DIR,
    DATABASE_PACKAGE_DIR,
    ENV_EXAMPLE_FILE_PATH,
    ENV_FILE_PATH,
    LOG_DIR,
    PROJECT_ROOT,
    ensure_directory,
    resolve_within_project,
)
from app.config.security import (
    ALLOWED_ATTACHMENT_CONTENT_TYPES,
    ATTACHMENTS_STORAGE_BUCKET,
    AUTHORIZATION_HEADER_NAME,
    BEARER_AUTH_SCHEME,
    MAX_ATTACHMENT_SIZE_BYTES,
    SENSITIVE_ENV_VAR_NAMES,
    is_sensitive_env_var,
    redact_mapping_for_logging,
    redact_secret,
)
from app.config.settings import (
    AppSettings,
    InvitationSettings,
    LoggingSettings,
    RateLimitSettings,
    SchedulerSettings,
    SmtpSettings,
    WorkflowSettings,
    load_settings,
)

__all__ = [
    # constants
    "API_VERSION_PREFIX",
    "APP_NAME",
    "APP_SHORT_NAME",
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "VALID_LOG_LEVELS",
    # environment
    "DEFAULT_ENVIRONMENT",
    "Environment",
    "detect_environment",
    # exceptions
    "ConfigurationError",
    "EnvironmentDetectionError",
    "InvalidConfigurationValueError",
    "LoggingConfigurationError",
    "MissingEnvironmentVariableError",
    # logging_config
    "StructuredFormatter",
    "configure_logging",
    "get_logger",
    # paths
    "APP_DIR",
    "CONFIG_PACKAGE_DIR",
    "DATABASE_MIGRATIONS_DIR",
    "DATABASE_PACKAGE_DIR",
    "ENV_EXAMPLE_FILE_PATH",
    "ENV_FILE_PATH",
    "LOG_DIR",
    "PROJECT_ROOT",
    "ensure_directory",
    "resolve_within_project",
    # security
    "ALLOWED_ATTACHMENT_CONTENT_TYPES",
    "ATTACHMENTS_STORAGE_BUCKET",
    "AUTHORIZATION_HEADER_NAME",
    "BEARER_AUTH_SCHEME",
    "MAX_ATTACHMENT_SIZE_BYTES",
    "SENSITIVE_ENV_VAR_NAMES",
    "is_sensitive_env_var",
    "redact_mapping_for_logging",
    "redact_secret",
    # settings
    "AppSettings",
    "InvitationSettings",
    "LoggingSettings",
    "RateLimitSettings",
    "SchedulerSettings",
    "SmtpSettings",
    "WorkflowSettings",
    "load_settings",
]
