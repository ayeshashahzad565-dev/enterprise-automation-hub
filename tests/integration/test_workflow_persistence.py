"""Real-database tests for workflow definition/stage persistence and
read access, exercising the actual JSONB round-trip and ordering
guarantees ``WorkflowStageRepository``/``WorkflowDefinitionRepository``
depend on.
"""

from __future__ import annotations

import uuid

import pytest

from app.models.enums import StageStatus, UserRole
from tests.fixtures.factories import department_queue_stage, specific_user_stage

pytestmark = pytest.mark.integration


class TestWorkflowDefinitionPersistence:
    def test_the_full_stage_document_round_trips_through_jsonb(self, real_repos, make_test_profile):
        admin = make_test_profile(role=UserRole.ADMIN)
        approver = make_test_profile(role=UserRole.APPROVER)
        request_type = f"itest_{uuid.uuid4().hex[:8]}"
        stages = [
            specific_user_stage(1, "Manager Review", user_id=approver.id, escalation_hours=12),
            department_queue_stage(
                2, "Finance Review", role=UserRole.APPROVER, department="finance"
            ),
        ]

        created = real_repos.workflow_definition.create_definition(
            request_type=request_type, version=1, definition={"stages": stages}, created_by=admin.id
        )
        reloaded = real_repos.workflow_definition.get_by_id(created.id)

        assert len(reloaded.definition["stages"]) == 2
        assert reloaded.definition["stages"][0]["assignment_strategy"] == "specific_user"
        assert reloaded.definition["stages"][0]["escalation_hours"] == 12
        assert reloaded.definition["stages"][1]["assignment_strategy"] == "department_queue"
        assert reloaded.definition["stages"][1]["department"] == "finance"


class TestWorkflowStagePersistence:
    def test_stages_are_listed_in_ascending_stage_order(self, real_repos, make_test_profile):
        employee = make_test_profile(role=UserRole.EMPLOYEE)
        admin = make_test_profile(role=UserRole.ADMIN)
        approver = make_test_profile(role=UserRole.APPROVER)
        request_type = f"itest_{uuid.uuid4().hex[:8]}"
        definition = real_repos.workflow_definition.create_definition(
            request_type=request_type, version=1, definition={"stages": []}, created_by=admin.id
        )
        request = real_repos.request.create_request(
            requester_id=employee.id,
            workflow_definition_id=definition.id,
            request_type=request_type,
            title="Multi-stage persistence test",
        )
        # Intentionally created out of order to prove the repository
        # sorts by stage_order rather than insertion order.
        real_repos.workflow_stage.create_stage(
            request_id=request.id,
            stage_order=2,
            stage_name="Finance Review",
            assigned_to=approver.id,
        )
        real_repos.workflow_stage.create_stage(
            request_id=request.id,
            stage_order=1,
            stage_name="Manager Review",
            assigned_to=approver.id,
        )

        stages = real_repos.workflow_stage.list_for_request(request.id).items

        assert [s.stage_order for s in stages] == [1, 2]
        assert [s.stage_name for s in stages] == ["Manager Review", "Finance Review"]

    def test_get_highest_stage_order_reflects_persisted_stages(self, real_repos, make_test_profile):
        employee = make_test_profile(role=UserRole.EMPLOYEE)
        admin = make_test_profile(role=UserRole.ADMIN)
        approver = make_test_profile(role=UserRole.APPROVER)
        request_type = f"itest_{uuid.uuid4().hex[:8]}"
        definition = real_repos.workflow_definition.create_definition(
            request_type=request_type, version=1, definition={"stages": []}, created_by=admin.id
        )
        request = real_repos.request.create_request(
            requester_id=employee.id,
            workflow_definition_id=definition.id,
            request_type=request_type,
            title="Highest order test",
        )
        assert real_repos.workflow_stage.get_highest_stage_order(request.id) == 0

        real_repos.workflow_stage.create_stage(
            request_id=request.id,
            stage_order=1,
            stage_name="Manager Review",
            assigned_to=approver.id,
        )
        assert real_repos.workflow_stage.get_highest_stage_order(request.id) == 1

    def test_list_decided_for_request_excludes_pending_stages(self, real_repos, make_test_profile):
        employee = make_test_profile(role=UserRole.EMPLOYEE)
        admin = make_test_profile(role=UserRole.ADMIN)
        approver = make_test_profile(role=UserRole.APPROVER)
        request_type = f"itest_{uuid.uuid4().hex[:8]}"
        definition = real_repos.workflow_definition.create_definition(
            request_type=request_type, version=1, definition={"stages": []}, created_by=admin.id
        )
        request = real_repos.request.create_request(
            requester_id=employee.id,
            workflow_definition_id=definition.id,
            request_type=request_type,
            title="Decided stages test",
        )
        decided_stage = real_repos.workflow_stage.create_stage(
            request_id=request.id,
            stage_order=1,
            stage_name="Manager Review",
            assigned_to=approver.id,
        )
        real_repos.workflow_stage.create_stage(
            request_id=request.id,
            stage_order=2,
            stage_name="Finance Review",
            assigned_to=approver.id,
        )
        real_repos.approval.approve_stage(
            decided_stage.id, expected_version=1, decided_by=approver.id
        )

        decided = real_repos.workflow_stage.list_decided_for_request(request.id).items

        assert len(decided) == 1
        assert decided[0].status is StageStatus.APPROVED
