"""Repository Layer for the Enterprise Automation Hub.

Per the Architecture Design Document, this is the only package in the
codebase permitted to construct and issue queries against the Supabase
client. Every repository exposed here performs persistence only — no
business rule enforcement, no orchestration across multiple repositories
(that is the Application Layer's responsibility), and no direct handling
of HTTP concerns.

This module re-exports every repository class, record dataclass, and enum
defined across the individual repository modules, so that calling code can
import from ``app.database.repositories`` directly rather than reaching
into each submodule.
"""

from __future__ import annotations

from app.database.repositories.analytics_repository import (
    AnalyticsRepository,
    ApprovalThroughput,
    StatusBreakdown,
    VolumeByKey,
)
from app.database.repositories.approval_repository import ApprovalRepository
from app.database.repositories.audit_repository import AuditLogRecord, AuditRepository
from app.database.repositories.base_repository import Page, PagedResult
from app.database.repositories.invitation_repository import (
    InvitationRecord,
    InvitationRepository,
    InvitationStatus,
)
from app.database.repositories.job_repository import JobRecord, JobRepository
from app.database.repositories.notification_preference_repository import (
    NotificationPreferenceRecord,
    NotificationPreferenceRepository,
)
from app.database.repositories.notification_repository import (
    NotificationRecord,
    NotificationRepository,
    NotificationType,
)
from app.database.repositories.request_repository import (
    RequestRecord,
    RequestRepository,
    RequestStatus,
)
from app.database.repositories.user_repository import ProfileRecord, ProfileRepository, UserRole
from app.database.repositories.workflow_repository import (
    StageStatus,
    WorkflowDefinitionRecord,
    WorkflowDefinitionRepository,
    WorkflowStageRecord,
    WorkflowStageRepository,
)

__all__ = [
    "AnalyticsRepository",
    "ApprovalRepository",
    "ApprovalThroughput",
    "AuditLogRecord",
    "AuditRepository",
    "InvitationRecord",
    "InvitationRepository",
    "InvitationStatus",
    "JobRecord",
    "JobRepository",
    "NotificationPreferenceRecord",
    "NotificationPreferenceRepository",
    "NotificationRecord",
    "NotificationRepository",
    "NotificationType",
    "Page",
    "PagedResult",
    "ProfileRecord",
    "ProfileRepository",
    "RequestRecord",
    "RequestRepository",
    "RequestStatus",
    "StageStatus",
    "StatusBreakdown",
    "UserRole",
    "VolumeByKey",
    "WorkflowDefinitionRecord",
    "WorkflowDefinitionRepository",
    "WorkflowStageRecord",
    "WorkflowStageRepository",
]
