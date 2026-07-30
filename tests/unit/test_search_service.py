"""Unit tests for ``app.services.search_service.GlobalSearchService``."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.database.repositories.base_repository import Page
from app.models.enums import NotificationType, UserRole
from app.services.exceptions import NotFoundError, ValidationError
from app.services.search_service import _fuzzy_score, _highlight_snippet
from tests.fixtures.factories import specific_user_stage

pytestmark = pytest.mark.unit


class TestSearchValidation:
    def test_empty_query_raises_validation_error(self, env, employee):
        _, employee_identity = employee

        with pytest.raises(ValidationError):
            env.search_service.search(employee_identity, "   ")


class TestRequestSearch:
    def test_employee_only_finds_their_own_requests(
        self, env, employee, make_user, approver, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="Laptop purchase"
        )
        _, other_identity = make_user(role=UserRole.EMPLOYEE, full_name="Other Employee")
        env.request_service.create_request(
            other_identity, request_type="expense_reimbursement", title="Laptop for other team"
        )

        results = env.search_service.search(
            employee_identity, "Laptop", entity_types=["request"]
        ).items

        assert [r.title for r in results] == ["Laptop purchase"]
        assert results[0].entity_type == "request"
        assert results[0].request_id == results[0].id

    def test_approver_only_finds_requests_assigned_to_them(
        self, env, employee, approver, second_approver, make_definition
    ):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        second_approver_profile, _ = second_approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        make_definition(
            request_type="equipment_request",
            stages=[specific_user_stage(1, "Manager Review", user_id=second_approver_profile.id)],
        )
        env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="Widget order"
        )
        env.request_service.create_request(
            employee_identity, request_type="equipment_request", title="Widget for other approver"
        )

        results = env.search_service.search(
            approver_identity, "Widget", entity_types=["request"]
        ).items

        assert [r.title for r in results] == ["Widget order"]


class TestApprovalSearch:
    def test_employee_gets_no_approval_results(self, env, employee):
        _, employee_identity = employee

        results = env.search_service.search(
            employee_identity, "anything", entity_types=["approval"]
        ).items

        assert results == []

    def test_approver_finds_pending_stage_by_request_title(
        self, env, employee, approver, make_definition
    ):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        created = env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="Conference travel"
        )

        results = env.search_service.search(
            approver_identity, "Conference", entity_types=["approval"]
        ).items

        assert len(results) == 1
        assert results[0].entity_type == "approval"
        assert results[0].request_id == created.id
        assert results[0].stage is not None
        assert results[0].stage.request_id == created.id

    def test_unrelated_query_does_not_match_pending_stage(
        self, env, employee, approver, make_definition
    ):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="Conference travel"
        )

        results = env.search_service.search(
            approver_identity, "zzz_completely_unrelated_zzz", entity_types=["approval"]
        ).items

        assert results == []


class TestWorkflowSearch:
    def test_non_admin_only_finds_active_definitions(
        self, env, employee, approver, admin, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )

        results = env.search_service.search(
            employee_identity, "expense", entity_types=["workflow"]
        ).items

        assert len(results) == 1
        assert results[0].request_type == "expense_reimbursement"

    def test_admin_finds_inactive_definitions_too(self, env, admin, approver):
        _, admin_identity = admin
        approver_profile, _ = approver
        env.workflow_definition_service.create_definition(
            admin_identity,
            request_type="unused_draft_type",
            definition={
                "stages": [specific_user_stage(1, "Solo Stage", user_id=approver_profile.id)]
            },
        )

        results = env.search_service.search(
            admin_identity, "unused_draft", entity_types=["workflow"]
        ).items

        assert len(results) == 1
        assert results[0].subtitle == "Inactive"


class TestUserSearch:
    def test_non_admin_never_gets_user_results(self, env, employee, approver):
        _, employee_identity = employee
        approver_profile, _ = approver

        results = env.search_service.search(
            employee_identity, approver_profile.full_name, entity_types=["user"]
        ).items

        assert results == []

    def test_admin_finds_users_by_name(self, env, admin, approver):
        _, admin_identity = admin
        approver_profile, _ = approver

        results = env.search_service.search(
            admin_identity, "Alan Approver", entity_types=["user"]
        ).items

        assert len(results) == 1
        assert results[0].id == approver_profile.id
        assert results[0].entity_type == "user"


class TestDepartmentSearch:
    def test_non_admin_never_gets_department_results(self, env, employee):
        _, employee_identity = employee

        results = env.search_service.search(
            employee_identity, "sales", entity_types=["department"]
        ).items

        assert results == []

    def test_admin_finds_a_department_by_name(self, env, admin, employee, approver):
        _, admin_identity = admin

        results = env.search_service.search(
            admin_identity, "sales", entity_types=["department"]
        ).items

        assert len(results) == 1
        assert results[0].entity_type == "department"
        assert results[0].title == "sales"
        assert results[0].subtitle == "2 members"

    def test_unrelated_query_does_not_match_a_department(self, env, admin, employee):
        _, admin_identity = admin

        results = env.search_service.search(
            admin_identity, "zzz_completely_unrelated_zzz", entity_types=["department"]
        ).items

        assert results == []


class TestNotificationSearch:
    def test_finds_the_callers_own_notification(self, env, employee, make_user):
        employee_profile, employee_identity = employee
        make_user(role=UserRole.EMPLOYEE, full_name="Other Employee")
        env.notification_repo.create_notification(
            recipient_id=employee_profile.id,
            notification_type=NotificationType.SYSTEM,
            message="Your kiwi request was approved",
        )

        results = env.search_service.search(
            employee_identity, "kiwi", entity_types=["notification"]
        ).items

        assert len(results) == 1
        assert results[0].entity_type == "notification"

    def test_never_returns_another_users_notification(self, env, employee, make_user):
        _, employee_identity = employee
        other_profile, _ = make_user(role=UserRole.EMPLOYEE, full_name="Other Employee")

        env.notification_repo.create_notification(
            recipient_id=other_profile.id,
            notification_type=NotificationType.SYSTEM,
            message="A durian update for someone else",
        )

        results = env.search_service.search(
            employee_identity, "durian", entity_types=["notification"]
        ).items

        assert results == []


class TestAttachmentSearch:
    def test_employee_only_finds_attachments_on_requests_they_can_view(
        self, env, employee, make_user, approver, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        mine = env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="Mine"
        )
        _, other_identity = make_user(role=UserRole.EMPLOYEE, full_name="Other Employee")
        theirs = env.request_service.create_request(
            other_identity, request_type="expense_reimbursement", title="Theirs"
        )
        env.attachment_repo.create_attachment(
            attachment_id=uuid4(),
            request_id=mine.id,
            uploaded_by=employee_identity.user_id,
            file_name="receipt-guava.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_path="a/b/receipt-guava.pdf",
            checksum_sha256="a" * 64,
        )
        env.attachment_repo.create_attachment(
            attachment_id=uuid4(),
            request_id=theirs.id,
            uploaded_by=other_identity.user_id,
            file_name="receipt-guava-2.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_path="a/b/receipt-guava-2.pdf",
            checksum_sha256="b" * 64,
        )

        results = env.search_service.search(
            employee_identity, "guava", entity_types=["attachment"]
        ).items

        assert len(results) == 1
        assert results[0].request_id == mine.id


class TestCommentSearch:
    def test_employee_only_finds_comments_on_requests_they_can_view(
        self, env, employee, make_user, approver, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        mine = env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="Mine"
        )
        _, other_identity = make_user(role=UserRole.EMPLOYEE, full_name="Other Employee")
        theirs = env.request_service.create_request(
            other_identity, request_type="expense_reimbursement", title="Theirs"
        )
        env.comment_service.add_comment(
            employee_identity, mine.id, body="Please expedite this pineapple order"
        )
        env.comment_service.add_comment(other_identity, theirs.id, body="Another pineapple comment")

        results = env.search_service.search(
            employee_identity, "pineapple", entity_types=["comment"]
        ).items

        assert len(results) == 1
        assert results[0].request_id == mine.id

    def test_admin_finds_comments_across_every_request(
        self, env, employee, approver, admin, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        created = env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="Something"
        )
        env.comment_service.add_comment(
            employee_identity, created.id, body="A very specific mango remark"
        )

        results = env.search_service.search(
            admin_identity, "mango", entity_types=["comment"]
        ).items

        assert len(results) == 1
        assert results[0].request_id == created.id


class TestAuditEntrySearch:
    def test_employee_finds_audit_entries_for_their_own_requests(
        self, env, employee, approver, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        created = env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="Audit me"
        )

        results = env.search_service.search(
            employee_identity, "CREATED", entity_types=["audit_entry"]
        ).items

        assert len(results) == 1
        assert results[0].request_id == created.id
        assert results[0].title == "Request Created"

    def test_employee_with_no_requests_finds_no_audit_entries(self, env, employee):
        _, employee_identity = employee

        results = env.search_service.search(
            employee_identity, "CREATED", entity_types=["audit_entry"]
        ).items

        assert results == []


class TestEntityTypeFiltering:
    def test_unfiltered_search_combines_multiple_entity_types_sorted_by_score(
        self, env, employee, approver, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="Zephyr project request"
        )

        results = env.search_service.search(employee_identity, "Zephyr").items

        entity_types_found = {r.entity_type for r in results}
        assert "request" in entity_types_found
        # Results must be sorted by descending score.
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)


class TestPagination:
    def test_page_size_bounds_the_returned_items_and_reports_total_records(
        self, env, employee, approver, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        for i in range(5):
            env.request_service.create_request(
                employee_identity,
                request_type="expense_reimbursement",
                title=f"Widget order {i}",
            )

        page1 = env.search_service.search(
            employee_identity, "Widget", entity_types=["request"], page=Page(number=1, size=2)
        )
        page2 = env.search_service.search(
            employee_identity, "Widget", entity_types=["request"], page=Page(number=2, size=2)
        )

        assert len(page1.items) == 2
        assert len(page2.items) == 2
        assert page1.total_records == 5
        assert page1.page == 1
        assert page2.page == 2
        assert {i.id for i in page1.items}.isdisjoint({i.id for i in page2.items})


class TestSearchHistory:
    def test_a_search_records_a_history_entry(self, env, employee):
        _, employee_identity = employee

        env.search_service.search(employee_identity, "anything", entity_types=["request"])

        recent = env.search_service.list_recent_searches(employee_identity)
        assert [r.query_text for r in recent] == ["anything"]

    def test_repeating_the_same_query_is_deduplicated_in_recent_searches(self, env, employee):
        _, employee_identity = employee

        env.search_service.search(employee_identity, "widgets", entity_types=["request"])
        env.search_service.search(employee_identity, "widgets", entity_types=["request"])
        env.search_service.search(employee_identity, "gadgets", entity_types=["request"])

        recent = env.search_service.list_recent_searches(employee_identity)

        assert [r.query_text for r in recent] == ["gadgets", "widgets"]

    def test_clear_search_history_empties_it(self, env, employee):
        _, employee_identity = employee
        env.search_service.search(employee_identity, "anything", entity_types=["request"])

        env.search_service.clear_search_history(employee_identity)

        assert env.search_service.list_recent_searches(employee_identity) == []

    def test_search_history_never_leaks_across_users(self, env, employee, make_user):
        _, employee_identity = employee
        _, other_identity = make_user(role=UserRole.EMPLOYEE, full_name="Other Employee")
        env.search_service.search(other_identity, "someone elses query", entity_types=["request"])

        recent = env.search_service.list_recent_searches(employee_identity)

        assert recent == []


class TestSavedFilters:
    def test_save_list_and_delete_round_trip(self, env, employee):
        _, employee_identity = employee

        created = env.search_service.save_filter(
            employee_identity, name="My filter", query_text="widgets", entity_types=["request"]
        )
        assert created.name == "My filter"
        assert [f.name for f in env.search_service.list_saved_filters(employee_identity)] == [
            "My filter"
        ]

        env.search_service.delete_saved_filter(employee_identity, created.id)

        assert env.search_service.list_saved_filters(employee_identity) == []

    def test_a_blank_name_is_rejected(self, env, employee):
        _, employee_identity = employee

        with pytest.raises(ValidationError):
            env.search_service.save_filter(employee_identity, name="   ", query_text="x")

    def test_one_user_cannot_delete_another_users_saved_filter(self, env, employee, make_user):
        _, employee_identity = employee
        _, other_identity = make_user(role=UserRole.EMPLOYEE, full_name="Other Employee")
        created = env.search_service.save_filter(
            employee_identity, name="Mine", query_text="widgets"
        )

        with pytest.raises(NotFoundError):
            env.search_service.delete_saved_filter(other_identity, created.id)

    def test_saved_filters_never_leak_across_users(self, env, employee, make_user):
        _, employee_identity = employee
        _, other_identity = make_user(role=UserRole.EMPLOYEE, full_name="Other Employee")
        env.search_service.save_filter(other_identity, name="Theirs", query_text="x")

        assert env.search_service.list_saved_filters(employee_identity) == []


class TestFuzzyScoreAndHighlight:
    def test_exact_substring_scores_higher_than_a_typo(self):
        exact = _fuzzy_score("laptop", "New laptop request")
        typo = _fuzzy_score("laptp", "New laptop request")

        assert exact > typo
        assert typo > 0.0

    def test_no_match_at_all_scores_low(self):
        score = _fuzzy_score("laptop", "completely unrelated text")

        assert score < 0.5

    def test_highlight_snippet_bolds_the_match(self):
        snippet = _highlight_snippet("Please buy a new laptop soon", "laptop")

        assert "**laptop**" in snippet

    def test_highlight_snippet_falls_back_to_plain_text_when_no_substring_match(self):
        snippet = _highlight_snippet("short text", "zzz")

        assert "**" not in snippet
        assert snippet == "short text"
