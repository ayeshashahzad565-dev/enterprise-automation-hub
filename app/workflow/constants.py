"""Fixed constants for the Workflow Engine.

Per WEDD Sections 3.5, 7.5, and 8, this module centralizes the small set
of fixed values the Workflow Engine's collaborators agree on — the
starting stage order, the escalation fallback role, and the fixed
audit-metadata marker keys/reason strings used when a fallback assignment
occurs — so that no collaborator module re-declares its own copy of any
of these.

This module defines no enum (those belong exclusively to
``app.models.enums``) and performs no logic; every value here is a
literal constant.
"""

from __future__ import annotations

from typing import Final

from app.models.enums import UserRole

__all__ = [
    "FIRST_STAGE_ORDER",
    "STAGE_ORDER_INCREMENT",
    "ESCALATION_FALLBACK_ROLE",
    "FALLBACK_REASON_NO_DEPARTMENT_APPROVER",
    "ASSIGNMENT_FALLBACK_METADATA_KEY",
]

#: The 1-indexed order of the first stage in any workflow definition,
#: per WEDD Section 3.5 and DSD Section 3.4's "1-indexed" convention.
FIRST_STAGE_ORDER: Final[int] = 1

#: The fixed increment between one stage's order and the next, per WEDD
#: Section 13.2's defensive check that stage generation is strictly
#: sequential.
STAGE_ORDER_INCREMENT: Final[int] = 1

#: The role a stage is reassigned to when its normal assignment strategy
#: cannot be resolved, per WEDD Section 7.5's fallback rule ("route to
#: administrator attention as a safety net") and Section 8.4's escalation
#: routing (which reuses this same fallback role).
ESCALATION_FALLBACK_ROLE: Final[UserRole] = UserRole.ADMIN

#: The fixed reason string recorded when the ``requester_manager``
#: assignment strategy cannot resolve a department-designated approver,
#: per WEDD Section 7.5 — the orchestrating Application Service is
#: expected to store this string in the corresponding ``audit_logs``
#: entry's ``metadata`` field under ``ASSIGNMENT_FALLBACK_METADATA_KEY``.
FALLBACK_REASON_NO_DEPARTMENT_APPROVER: Final[str] = (
    "No department-designated approver could be resolved for the requester's "
    "department; the stage was routed to administrator attention as a fallback, "
    "per WEDD Section 7.5."
)

#: The key under which a fallback-assignment marker should be recorded in
#: an ``audit_logs`` entry's ``metadata`` field, per WEDD Section 14.1's
#: note that this fallback is "recorded in metadata, not as a separate
#: action code."
ASSIGNMENT_FALLBACK_METADATA_KEY: Final[str] = "assignment_fallback_applied"
