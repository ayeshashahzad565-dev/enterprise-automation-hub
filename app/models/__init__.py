"""Domain Layer for the Enterprise Automation Hub.

Per the Architecture Design Document (ADD Section 3.3), this package
defines the Pydantic v2 models that describe the shape and invariants of
every entity in the system. It has zero dependencies on any other layer —
no Streamlit, no Supabase, no APScheduler, and no dependency on
``app.database`` — and is therefore the most heavily unit-testable part
of the codebase, exercised entirely through direct model construction
(TSD Section 3.5).

This module re-exports every model, enum, and exception defined across
the individual submodules, so that calling code can import from
``app.models`` directly rather than reaching into each submodule.
"""

from __future__ import annotations

from app.models.analytics import ApprovalThroughput, StatusBreakdown, VolumeByKey
from app.models.approval import (
    ApprovalDecisionRequest,
    ApprovalOutcome,
    EscalationOutcome,
    RejectionDecisionRequest,
)
from app.models.attachment import Attachment
from app.models.audit import AuditLogCreate, AuditLogEntry
from app.models.base import (
    EAHBaseModel,
    IdentifiedModel,
    PartialUpdateModel,
    SoftDeletableModel,
    TimestampedModel,
    UpdatableTimestampModel,
    UTCDatetime,
    VersionedModel,
)
from app.models.comment import Comment, CommentCreate
from app.models.enums import (
    AssignmentStrategy,
    AttachmentScanStatus,
    AuditAction,
    EffectiveInvitationStatus,
    InvitationStatus,
    JobPriority,
    JobStatus,
    NotificationType,
    RequestStatus,
    StageStatus,
    UserRole,
)
from app.models.exceptions import (
    DomainError,
    EmptyUpdatePayloadError,
    InvalidDecisionError,
    InvalidStageConfigurationError,
    InvalidWorkflowDefinitionError,
)
from app.models.invitation import Invitation, InvitationCreate
from app.models.job import Job, JobCreate
from app.models.notification import Notification, NotificationCreate
from app.models.notification_preference import NotificationPreference, NotificationPreferenceUpdate
from app.models.request import Request, RequestCreate, RequestUpdate
from app.models.user import Profile, ProfileCreate, ProfileUpdate
from app.models.workflow import (
    StageDefinition,
    WorkflowDefinition,
    WorkflowDefinitionCreate,
    WorkflowDefinitionDocument,
    WorkflowStage,
)

__all__ = [
    # analytics
    "ApprovalThroughput",
    "StatusBreakdown",
    "VolumeByKey",
    # approval
    "ApprovalDecisionRequest",
    "ApprovalOutcome",
    "EscalationOutcome",
    "RejectionDecisionRequest",
    # attachment
    "Attachment",
    # audit
    "AuditLogCreate",
    "AuditLogEntry",
    # base
    "EAHBaseModel",
    "IdentifiedModel",
    "PartialUpdateModel",
    "SoftDeletableModel",
    "TimestampedModel",
    "UpdatableTimestampModel",
    "UTCDatetime",
    "VersionedModel",
    # comment
    "Comment",
    "CommentCreate",
    # enums
    "AssignmentStrategy",
    "AttachmentScanStatus",
    "AuditAction",
    "EffectiveInvitationStatus",
    "InvitationStatus",
    "JobPriority",
    "JobStatus",
    "NotificationType",
    "RequestStatus",
    "StageStatus",
    "UserRole",
    # exceptions
    "DomainError",
    "EmptyUpdatePayloadError",
    "InvalidDecisionError",
    "InvalidStageConfigurationError",
    "InvalidWorkflowDefinitionError",
    # invitation
    "Invitation",
    "InvitationCreate",
    # job
    "Job",
    "JobCreate",
    # notification
    "Notification",
    "NotificationCreate",
    "NotificationPreference",
    "NotificationPreferenceUpdate",
    # request
    "Request",
    "RequestCreate",
    "RequestUpdate",
    # user
    "Profile",
    "ProfileCreate",
    "ProfileUpdate",
    # workflow
    "StageDefinition",
    "WorkflowDefinition",
    "WorkflowDefinitionCreate",
    "WorkflowDefinitionDocument",
    "WorkflowStage",
]
