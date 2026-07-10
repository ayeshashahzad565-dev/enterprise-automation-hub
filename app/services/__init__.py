"""The Application Service Layer for the Enterprise Automation Hub.

Per the Architecture Design Document, this package orchestrates every use
case the system performs by coordinating the already-finalized
Repository Layer (``app.database``), Domain Layer (``app.models``),
Workflow Engine (``app.workflow``), and Auth Layer (``app.auth``). It
contains no business rules that belong inside the Workflow Engine, no
SQL, and no Presentation Layer code.

This package contains:

- ``exceptions``: the centralized service-facing exception hierarchy,
  plus the ``translate_*`` functions every service uses to convert a
  lower-layer failure into it.
- ``workflow_definition_service``: workflow definition lifecycle
  orchestration, and ``TransactionContext``, the compensation-based
  orchestration boundary shared by every multi-step operation in this
  package.
- ``request_service``: request creation, editing, withdrawal, and reads.
- ``approval_service``: stage approval, rejection, escalation, and the
  pending-approvals queue.
- ``notification_service``: notification creation and delivery,
  including the ``EmailSender`` protocol every future SMTP
  implementation is expected to satisfy.
- ``analytics_service``: read-only aggregate queries for dashboards.
- ``dashboard_service``: a thin composition layer aggregating the four
  services above into a single presentation-ready DTO.

This module re-exports the public surface of every submodule so that
calling code (in particular, a future Presentation Layer package) can
import from ``app.services`` directly.
"""

from __future__ import annotations

from app.services.analytics_service import AnalyticsService
from app.services.approval_service import ApprovalService, map_workflow_stage_record_to_domain
from app.services.dashboard_service import DashboardService, DashboardSummary
from app.services.exceptions import (
    AssignmentError,
    ConcurrencyError,
    ConfigurationError,
    EAHError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
    WorkflowError,
    translate_auth_error,
    translate_database_error,
    translate_model_construction_error,
    translate_workflow_error,
)
from app.services.notification_service import (
    EmailSender,
    NotificationService,
    map_notification_record_to_domain,
)
from app.services.request_service import (
    RequestService,
    map_profile_record_to_domain,
    map_request_record_to_domain,
)
from app.services.workflow_definition_service import (
    TransactionContext,
    WorkflowDefinitionService,
    map_workflow_definition_record_to_domain,
)

__all__ = [
    # analytics_service
    "AnalyticsService",
    # approval_service
    "ApprovalService",
    "map_workflow_stage_record_to_domain",
    # dashboard_service
    "DashboardService",
    "DashboardSummary",
    # exceptions
    "AssignmentError",
    "ConcurrencyError",
    "ConfigurationError",
    "EAHError",
    "NotFoundError",
    "PermissionDeniedError",
    "ValidationError",
    "WorkflowError",
    "translate_auth_error",
    "translate_database_error",
    "translate_model_construction_error",
    "translate_workflow_error",
    # notification_service
    "EmailSender",
    "NotificationService",
    "map_notification_record_to_domain",
    # request_service
    "RequestService",
    "map_profile_record_to_domain",
    "map_request_record_to_domain",
    # workflow_definition_service
    "TransactionContext",
    "WorkflowDefinitionService",
    "map_workflow_definition_record_to_domain",
]