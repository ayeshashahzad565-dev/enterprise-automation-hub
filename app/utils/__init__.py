"""Shared, pure utility functions for the Enterprise Automation Hub.

Per the Architecture Design Document, this package holds cross-cutting,
stateless helpers with no business logic, no persistence access, and no
Presentation Layer dependency — the kind of small, generic function that
every other layer of the application (services, the Workflow Engine, and
any future API-binding layer) reaches for repeatedly. Every function in
this package is independently unit-testable in isolation, with no
database connection, no Supabase client, and no Streamlit context
required.

This module re-exports the public surface of every submodule so that
calling code can import from ``app.utils`` directly.
"""

from __future__ import annotations

from app.utils.datetime_utils import (
    add_hours,
    ensure_timezone_aware,
    format_iso8601,
    is_past,
    parse_iso8601,
    seconds_between,
    to_utc,
    utc_now,
)
from app.utils.decorators import deprecated, log_calls, suppress_and_log, timed
from app.utils.exceptions import (
    DeserializationError,
    FileValidationError,
    InputValidationError,
    PaginationParameterError,
    RetryExhaustedError,
    SerializationError,
    UtilityError,
)
from app.utils.file_utils import (
    build_storage_path,
    compute_sha256_checksum,
    get_file_extension,
    sanitize_filename,
    sniff_content_type,
    validate_content_type,
    validate_file_size,
)
from app.utils.helpers import chunked, coalesce, deep_get, first_or_default, truncate_string
from app.utils.id_generator import (
    generate_request_correlation_id,
    generate_uuid,
    generate_uuid_str,
)
from app.utils.pagination import (
    PaginationMetadata,
    PaginationParams,
    build_pagination_metadata,
    parse_pagination_params,
)
from app.utils.response import (
    ErrorCode,
    build_error_response,
    build_list_response,
    build_meta,
    build_success_response,
)
from app.utils.retry import DEFAULT_RETRY_POLICY, RetryPolicy, retry, retry_call
from app.utils.serialization import (
    deserialize,
    deserialize_json,
    deserialize_many,
    serialize,
    serialize_json,
    serialize_many,
)
from app.utils.validators import (
    is_valid_uuid,
    validate_email,
    validate_iso8601_datetime,
    validate_non_empty_string,
    validate_positive_integer,
    validate_positive_number,
    validate_string_length,
    validate_uuid,
)

__all__ = [
    # datetime_utils
    "add_hours",
    "ensure_timezone_aware",
    "format_iso8601",
    "is_past",
    "parse_iso8601",
    "seconds_between",
    "to_utc",
    "utc_now",
    # decorators
    "deprecated",
    "log_calls",
    "suppress_and_log",
    "timed",
    # exceptions
    "DeserializationError",
    "FileValidationError",
    "InputValidationError",
    "PaginationParameterError",
    "RetryExhaustedError",
    "SerializationError",
    "UtilityError",
    # file_utils
    "build_storage_path",
    "compute_sha256_checksum",
    "get_file_extension",
    "sanitize_filename",
    "sniff_content_type",
    "validate_content_type",
    "validate_file_size",
    # helpers
    "chunked",
    "coalesce",
    "deep_get",
    "first_or_default",
    "truncate_string",
    # id_generator
    "generate_request_correlation_id",
    "generate_uuid",
    "generate_uuid_str",
    # pagination
    "PaginationMetadata",
    "PaginationParams",
    "build_pagination_metadata",
    "parse_pagination_params",
    # response
    "ErrorCode",
    "build_error_response",
    "build_list_response",
    "build_meta",
    "build_success_response",
    # retry
    "DEFAULT_RETRY_POLICY",
    "RetryPolicy",
    "retry",
    "retry_call",
    # serialization
    "deserialize",
    "deserialize_json",
    "deserialize_many",
    "serialize",
    "serialize_json",
    "serialize_many",
    # validators
    "is_valid_uuid",
    "validate_email",
    "validate_iso8601_datetime",
    "validate_non_empty_string",
    "validate_positive_integer",
    "validate_positive_number",
    "validate_string_length",
    "validate_uuid",
]
