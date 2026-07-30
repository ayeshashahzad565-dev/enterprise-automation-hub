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

from enum import StrEnum


class UserRole(StrEnum):
    """The three roles fixed by DSD Section 1.5's ``user_role`` enum."""

    EMPLOYEE = "employee"
    APPROVER = "approver"
    ADMIN = "admin"


class RequestStatus(StrEnum):
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


class StageStatus(StrEnum):
    """The four values fixed by DSD Section 1.5's ``stage_status`` enum.

    ``SKIPPED`` is not produced by any assignment strategy in the current
    baseline; it exists as a forward-looking hook for conditional
    branching (WEDD Section 20.2).
    """

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SKIPPED = "skipped"


class NotificationType(StrEnum):
    """The six values fixed by DSD Section 1.5's ``notification_type`` enum."""

    ASSIGNMENT = "assignment"
    REMINDER = "reminder"
    ESCALATION = "escalation"
    DECISION = "decision"
    COMPLETION = "completion"
    SYSTEM = "system"


class AssignmentStrategy(StrEnum):
    """The three workflow-stage assignment strategies defined in DSD
    Section 5.2 and elaborated in WEDD Section 7."""

    SPECIFIC_USER = "specific_user"
    DEPARTMENT_QUEUE = "department_queue"
    REQUESTER_MANAGER = "requester_manager"


class AuditAction(StrEnum):
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
    PROFILE_DEACTIVATED = "PROFILE_DEACTIVATED"
    PROFILE_REACTIVATED = "PROFILE_REACTIVATED"
    PROFILE_ERASED = "PROFILE_ERASED"
    INVITATION_CREATED = "INVITATION_CREATED"
    INVITATION_RESENT = "INVITATION_RESENT"
    INVITATION_REVOKED = "INVITATION_REVOKED"
    INVITATION_ACCEPTED = "INVITATION_ACCEPTED"
    JOB_RETRIED = "JOB_RETRIED"
    SCHEDULED_JOB_ENABLED = "SCHEDULED_JOB_ENABLED"
    SCHEDULED_JOB_DISABLED = "SCHEDULED_JOB_DISABLED"
    SCHEDULED_JOB_TRIGGERED = "SCHEDULED_JOB_TRIGGERED"
    COMPANY_CREATED = "COMPANY_CREATED"
    COMPANY_SUSPENDED = "COMPANY_SUSPENDED"
    COMPANY_REACTIVATED = "COMPANY_REACTIVATED"
    COMPANY_DELETED = "COMPANY_DELETED"
    COMPANY_RESTORED = "COMPANY_RESTORED"
    COMPANY_SETTINGS_UPDATED = "COMPANY_SETTINGS_UPDATED"
    COMPANY_LICENSE_UPDATED = "COMPANY_LICENSE_UPDATED"
    FEATURE_FLAG_UPDATED = "FEATURE_FLAG_UPDATED"


class AttachmentScanStatus(StrEnum):
    """The virus-scan status of an attachment's stored file content.

    No virus/malware scanner is integrated in this baseline (API-ADD
    Section 23 states this plainly) — ``SKIPPED`` is therefore the only
    value ``app.services.virus_scanner.NullVirusScanner`` ever produces.
    ``CLEAN``/``INFECTED``/``SCAN_ERROR`` exist so that a real scanner can
    be plugged in later (``app.services.virus_scanner.VirusScanner`` is
    the integration point) without a schema change: the column and this
    enum already exist, honestly defaulting to "not actually scanned"
    rather than a fabricated "clean" result.
    """

    SKIPPED = "skipped"
    CLEAN = "clean"
    INFECTED = "infected"
    SCAN_ERROR = "scan_error"


class InvitationStatus(StrEnum):
    """The three values fixed by the ``user_invitations.status`` check
    constraint (Enterprise User Onboarding architecture, Milestone 1).

    ``EXPIRED`` is intentionally absent — it is derived from
    ``expires_at`` at read time, not persisted, so a background sweep is
    never required to keep this status accurate.
    """

    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"


class EffectiveInvitationStatus(StrEnum):
    """The four-value status an invitation presents to a caller, computed
    by ``app.services.invitation_service`` from ``InvitationStatus`` plus
    ``expires_at`` — never persisted (see ``InvitationStatus``).

    ``PENDING`` and ``EXPIRED`` both correspond to a persisted status of
    ``InvitationStatus.PENDING``; which one applies depends on whether
    ``expires_at`` has passed at the moment of the read.
    """

    PENDING = "pending"
    EXPIRED = "expired"
    ACCEPTED = "accepted"
    REVOKED = "revoked"


class JobStatus(StrEnum):
    """The lifecycle states of a row in the ``jobs`` table.

    ``QUEUED`` and ``RETRYING`` both mean "waiting to be picked up by a
    worker" — they are distinguished only so the admin dashboard can show
    whether a job is on its first attempt or has already failed at least
    once. ``DEAD_LETTERED`` is terminal until an operator explicitly
    retries it (``JobRepository.retry_dead_letter``), which resets the
    row back to ``QUEUED``.
    """

    QUEUED = "queued"
    RUNNING = "running"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    DEAD_LETTERED = "dead_lettered"


class JobPriority(StrEnum):
    """The three priority tiers a job may be enqueued at.

    Each tier maps to its own Redis ready-list per queue
    (``app.jobs.redis_queue.RedisJobQueue``), consumed in ``HIGH``,
    ``NORMAL``, ``LOW`` order by default, with periodic order reversal to
    bound starvation of lower tiers under sustained load.
    """

    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"
