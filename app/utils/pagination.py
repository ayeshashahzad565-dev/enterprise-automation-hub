"""Pagination request parsing and response metadata construction.

Per API-ADD Sections 3.9 and 12, every list endpoint accepts ``page`` and
``page_size`` query parameters (defaulting to 1 and 20, capped at 100) and
returns a ``pagination`` object (``page``, ``page_size``,
``total_records``, ``total_pages``) alongside its results. This module
provides the two corresponding utilities: validating raw, caller-supplied
pagination parameters into a bounded, typed request, and constructing the
exact response metadata shape the API-ADD specifies from a query's result
count.

This module is deliberately independent of ``app.database`` — the
persistence-level pagination primitives in
``app.database.repositories.base_repository`` (``Page``, ``PagedResult``)
exist to build Supabase ``.range()`` queries and are a Repository Layer
concern; this module exists one layer up, for validating a raw request's
pagination parameters and shaping a response's pagination metadata,
independent of how the underlying data was actually fetched.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from app.config.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.utils.exceptions import PaginationParameterError

__all__ = [
    "PaginationParams",
    "PaginationMetadata",
    "parse_pagination_params",
    "build_pagination_metadata",
]


@dataclass(frozen=True, slots=True)
class PaginationParams:
    """A validated, bounded pagination request.

    Attributes:
        page: The 1-indexed page number requested.
        page_size: The number of records requested per page.
    """

    page: int
    page_size: int


@dataclass(frozen=True, slots=True)
class PaginationMetadata:
    """The pagination metadata shape returned alongside a list response,
    matching API-ADD Section 9's ``pagination`` object exactly.

    Attributes:
        page: The page number that was served.
        page_size: The page size that was served.
        total_records: The total number of records matching the query,
            across all pages.
        total_pages: ``ceil(total_records / page_size)``.
    """

    page: int
    page_size: int
    total_records: int
    total_pages: int

    def to_dict(self) -> dict[str, int]:
        """Return this metadata as a plain dict, ready for inclusion in
        an API response's ``pagination`` field.

        Returns:
            A dict with keys ``page``, ``page_size``, ``total_records``,
            and ``total_pages``.
        """
        return {
            "page": self.page,
            "page_size": self.page_size,
            "total_records": self.total_records,
            "total_pages": self.total_pages,
        }


def parse_pagination_params(
    page: int | str | None = None,
    page_size: int | str | None = None,
) -> PaginationParams:
    """Validate and bound raw pagination parameters.

    Per API-ADD Section 12: pagination is mandatory, and a ``page_size``
    above the documented maximum is rejected outright, never silently
    clamped.

    Args:
        page: The raw page number, as an int, a numeric string, or
            ``None``. Defaults to ``1`` when ``None``.
        page_size: The raw page size, as an int, a numeric string, or
            ``None``. Defaults to ``DEFAULT_PAGE_SIZE`` (20) when
            ``None``.

    Returns:
        A validated ``PaginationParams``.

    Raises:
        PaginationParameterError: If ``page`` is not a positive integer,
            or ``page_size`` is not an integer in the range
            ``[1, MAX_PAGE_SIZE]``.
    """
    resolved_page = _coerce_positive_int(page, default=1, field_name="page")
    if resolved_page < 1:
        raise PaginationParameterError(f"'page' must be >= 1, got {resolved_page}.")

    resolved_page_size = _coerce_positive_int(
        page_size, default=DEFAULT_PAGE_SIZE, field_name="page_size"
    )
    if not (1 <= resolved_page_size <= MAX_PAGE_SIZE):
        raise PaginationParameterError(
            f"'page_size' must be between 1 and {MAX_PAGE_SIZE}, got {resolved_page_size}."
        )

    return PaginationParams(page=resolved_page, page_size=resolved_page_size)


def build_pagination_metadata(
    *, page: int, page_size: int, total_records: int
) -> PaginationMetadata:
    """Construct pagination response metadata from a query's result count.

    Args:
        page: The page number that was served.
        page_size: The page size that was served.
        total_records: The total number of records matching the query,
            across all pages.

    Returns:
        A ``PaginationMetadata`` instance with ``total_pages`` computed
        as ``ceil(total_records / page_size)``.

    Raises:
        PaginationParameterError: If ``page_size`` is not positive, or
            ``total_records`` is negative.
    """
    if page_size < 1:
        raise PaginationParameterError(f"'page_size' must be >= 1, got {page_size}.")
    if total_records < 0:
        raise PaginationParameterError(f"'total_records' must be >= 0, got {total_records}.")
    total_pages = ceil(total_records / page_size) if total_records > 0 else 0
    return PaginationMetadata(
        page=page,
        page_size=page_size,
        total_records=total_records,
        total_pages=total_pages,
    )


def _coerce_positive_int(value: int | str | None, *, default: int, field_name: str) -> int:
    """Coerce a raw pagination parameter into an integer.

    Args:
        value: The raw value to coerce.
        default: The value to return if ``value`` is ``None``.
        field_name: The name of the field being coerced, for error
            attribution.

    Returns:
        The coerced integer.

    Raises:
        PaginationParameterError: If ``value`` is not ``None`` and cannot
            be parsed as an integer.
    """
    if value is None:
        return default
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise PaginationParameterError(
            f"'{field_name}' must be an integer, got {value!r}."
        ) from exc