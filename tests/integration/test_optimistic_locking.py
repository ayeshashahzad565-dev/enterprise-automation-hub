"""Real-database optimistic-locking tests.

Verifies ``BaseRepository.update_with_optimistic_lock``'s actual
``UPDATE ... WHERE id = :id AND version = :expected_version`` behavior
against genuine Postgres/postgrest — not a simulated version check.
"""

from __future__ import annotations

import uuid

import pytest

from app.database.exceptions import ConcurrentUpdateError
from app.models.enums import UserRole
from tests.fixtures.factories import specific_user_stage

pytestmark = pytest.mark.integration


class TestOptimisticLockingAgainstRealPostgres:
    def test_a_stale_version_update_is_rejected_by_the_real_database(
        self, real_repos, make_test_profile
    ):
        employee = make_test_profile(role=UserRole.EMPLOYEE)
        admin = make_test_profile(role=UserRole.ADMIN)
        approver = make_test_profile(role=UserRole.APPROVER)
        request_type = f"itest_{uuid.uuid4().hex[:8]}"
        definition = real_repos.workflow_definition.create_definition(
            request_type=request_type,
            version=1,
            definition={"stages": [specific_user_stage(1, "Manager Review", user_id=approver.id)]},
            created_by=admin.id,
        )
        request = real_repos.request.create_request(
            requester_id=employee.id,
            workflow_definition_id=definition.id,
            request_type=request_type,
            title="Optimistic lock test",
        )
        stage = real_repos.workflow_stage.create_stage(
            request_id=request.id,
            stage_order=1,
            stage_name="Manager Review",
            assigned_to=approver.id,
        )
        assert stage.version == 1

        # First decision, at the version the stage was actually created
        # with, succeeds and bumps the real row's version in Postgres.
        decided = real_repos.approval.approve_stage(
            stage.id, expected_version=1, decided_by=approver.id
        )
        assert decided.version == 2

        # A second decision submitted against the now-stale version 1 —
        # simulating a second caller who read the stage before the first
        # decision committed — is rejected by the real database's
        # `WHERE version = 1` predicate matching zero rows.
        with pytest.raises(ConcurrentUpdateError):
            real_repos.approval.approve_stage(stage.id, expected_version=1, decided_by=approver.id)

    def test_a_correct_version_update_succeeds_and_increments_the_version(
        self, real_repos, make_test_profile
    ):
        employee = make_test_profile(role=UserRole.EMPLOYEE, full_name="Version Bump Tester")

        updated = real_repos.profile.update_profile(
            employee.id, expected_version=employee.version, full_name="Renamed"
        )

        assert updated.version == employee.version + 1
        assert updated.full_name == "Renamed"

        reloaded = real_repos.profile.get_by_id(employee.id)
        assert reloaded.version == updated.version
