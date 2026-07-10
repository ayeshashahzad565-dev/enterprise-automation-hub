"""Centralized enumerations for the Domain Layer.

Every enum used anywhere in ``app.models`` is defined exactly once, here,
and imported by name elsewhere in this package — no other module in
``app.models`` defines its own enum. Every member's value below is a
lowercase string matching the corresponding native PostgreSQL enum type
defined in the Database Schema Design Document (DSD Section 1.5) exactly,
so that a member's ``.value`` can be sent to, or was received from, the
persistence layer without any translation step.
"""

from __future__ import annotations

from enum import Enum


class UserRole(str, Enum):
    """The three roles fixed by DSD Section 1.5's ``user_role`` enum."""

    EMPLOYEE = "employee"
    APPROVER = "approver"
    ADMIN = "admin"


class RequestStatus(str, Enum):
    """The five values fixed by DSD Section 1.5's ``request_status`` enum.

    ``APPROVED`` is reserved for forward compatibility (WEDD Section
    20.1) and is not reachable through any code path in the current
    baseline; ``COMPLETED`` is the terminal "approved" state a request
    actually reaches.
    """

    PENDING = "pending"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"


class StageStatus(str, Enum):
    """The four values fixed by DSD Section 1.5's ``stage_status`` enum.

    ``SKIPPED`` is not produced by any assignment strategy in the current
    baseline; it exists as a forward-looking hook for conditional
    branching (WEDD Section 20.2).
    """

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SKIPPED = "skipped"


class NotificationType(str, Enum):
    """The six values fixed by DSD Section 1.5's ``notification_type`` enum."""

    ASSIGNMENT = "assignment"
    REMINDER = "reminder"
    ESCALATION = "escalation"
    DECISION = "decision"
    COMPLETION = "completion"
    SYSTEM = "system"


class AssignmentStrategy(str, Enum):
    """The three workflow-stage assignment strategies defined in DSD
    Section 5.2 and elaborated in WEDD Section 7."""

    SPECIFIC_USER = "specific_user"
    DEPARTMENT_QUEUE = "department_queue"
    REQUESTER_MANAGER = "requester_manager"


class AuditAction(str, Enum):
    """The fixed set of audit action codes enumerated in WEDD Section 14.1.

    The underlying ``audit_logs.action`` database column is a plain
    ``text`` column (DSD Section 3.8), not a native enum — this Domain
    Layer enum exists to give calling code type safety and
    autocompletion over the fixed vocabulary of action codes the system
    actually produces, without requiring a corresponding database-level
    enum type.
    """

    REQUEST_CREATED = "REQUEST_CREATED"
    REQUEST_WITHDRAWN = "REQUEST_WITHDRAWN"
    STAGE_APPROVED = "STAGE_APPROVED"
    STAGE_REJECTED = "STAGE_REJECTED"
    STAGE_ESCALATED = "STAGE_ESCALATED"
    WORKFLOW_DEFINITION_ACTIVATED = "WORKFLOW_DEFINITION_ACTIVATED"
    COMMENT_CREATED = "COMMENT_CREATED"
    COMMENT_REMOVED = "COMMENT_REMOVED"
    ATTACHMENT_UPLOADED = "ATTACHMENT_UPLOADED"
    ATTACHMENT_REMOVED = "ATTACHMENT_REMOVED"
    PROFILE_UPDATED = "PROFILE_UPDATED"