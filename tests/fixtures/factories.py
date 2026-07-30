"""Plain (non-fixture) helper functions for building workflow definition
JSON documents in tests.

These build the raw ``dict`` shape ``WorkflowDefinitionDocument`` (and, in
turn, ``WorkflowDefinitionService.create_definition``) expects — one
function per assignment strategy in WEDD Section 7, so a test can build a
multi-stage definition declaratively without repeating the field shape.
"""

from __future__ import annotations

from uuid import UUID

from app.models.enums import UserRole

__all__ = ["specific_user_stage", "department_queue_stage", "requester_manager_stage"]


def specific_user_stage(
    order: int, name: str, *, user_id: UUID, escalation_hours: float = 24.0
) -> dict[str, object]:
    """Build a ``specific_user`` stage definition dict (WEDD Section 7.2)."""
    return {
        "order": order,
        "name": name,
        "assignment_strategy": "specific_user",
        "assigned_user_id": user_id,
        "escalation_hours": escalation_hours,
    }


def department_queue_stage(
    order: int, name: str, *, role: UserRole, department: str, escalation_hours: float = 24.0
) -> dict[str, object]:
    """Build a ``department_queue`` stage definition dict (WEDD Section 7.3)."""
    return {
        "order": order,
        "name": name,
        "assignment_strategy": "department_queue",
        "assigned_role": role.value,
        "department": department,
        "escalation_hours": escalation_hours,
    }


def requester_manager_stage(
    order: int, name: str, *, escalation_hours: float = 24.0
) -> dict[str, object]:
    """Build a ``requester_manager`` stage definition dict (WEDD Section 7.4)."""
    return {
        "order": order,
        "name": name,
        "assignment_strategy": "requester_manager",
        "escalation_hours": escalation_hours,
    }
