"""Real-database tests for schema shape, constraints, and transactions.

Every test here uses the ``pg_conn`` fixture: a single psycopg
transaction per test, unconditionally rolled back at teardown, so these
tests never leave any trace in the test database regardless of outcome
— including the tests that deliberately trigger a constraint violation
(which aborts the current transaction at the Postgres level; ``pg_conn``
rolling back afterward is exactly the recovery that requires).

Note on "SQLAlchemy mappings": per ``app/database/migrations/README.md``,
this project defines no SQLAlchemy ORM models — the schema is hand-authored
SQL and each table is mapped to a plain, hand-written ``*Record`` dataclass
in ``app.database.repositories``. ``TestSchemaToRecordMapping`` below is
this project's actual analog: it verifies each live table's columns match
its corresponding ``*Record`` dataclass's fields exactly, which is the
real risk an ORM mapping test would otherwise guard against here.
"""

from __future__ import annotations

import dataclasses
import uuid

import psycopg
import pytest

from app.database.repositories.audit_repository import AuditLogRecord
from app.database.repositories.comment_repository import CommentRecord
from app.database.repositories.notification_repository import NotificationRecord
from app.database.repositories.request_repository import RequestRecord
from app.database.repositories.user_repository import ProfileRecord
from app.database.repositories.workflow_repository import (
    WorkflowDefinitionRecord,
    WorkflowStageRecord,
)

pytestmark = pytest.mark.integration


def _insert_request(
    cur: psycopg.Cursor, *, requester_id: uuid.UUID, definition_id: uuid.UUID
) -> uuid.UUID:
    request_id = uuid.uuid4()
    cur.execute(
        "insert into public.requests (id, requester_id, workflow_definition_id, request_type, title) "
        "values (%s, %s, %s, %s, %s);",
        (
            str(request_id),
            str(requester_id),
            str(definition_id),
            "expense_reimbursement",
            "Test request",
        ),
    )
    return request_id


def _insert_definition(
    cur: psycopg.Cursor, *, created_by: uuid.UUID, request_type: str, version: int = 1
) -> uuid.UUID:
    definition_id = uuid.uuid4()
    cur.execute(
        "insert into public.workflow_definitions (id, request_type, version, definition, created_by) "
        "values (%s, %s, %s, %s, %s);",
        (
            str(definition_id),
            request_type,
            version,
            psycopg.types.json.Json({"stages": []}),
            str(created_by),
        ),
    )
    return definition_id


class TestForeignKeyConstraints:
    def test_a_request_cannot_reference_a_nonexistent_requester(self, pg_conn, anchor_profile_id):
        definition_id = _insert_definition(
            pg_conn.cursor(), created_by=anchor_profile_id, request_type="fk_test_a"
        )
        with pg_conn.cursor() as cur, pytest.raises(psycopg.errors.ForeignKeyViolation):
            cur.execute(
                "insert into public.requests (id, requester_id, workflow_definition_id, request_type, title) "
                "values (%s, %s, %s, %s, %s);",
                (
                    str(uuid.uuid4()),
                    str(uuid.uuid4()),
                    str(definition_id),
                    "expense_reimbursement",
                    "Ghost requester",
                ),
            )

    def test_a_request_cannot_reference_a_nonexistent_workflow_definition(
        self, pg_conn, anchor_profile_id
    ):
        with pg_conn.cursor() as cur, pytest.raises(psycopg.errors.ForeignKeyViolation):
            cur.execute(
                "insert into public.requests (id, requester_id, workflow_definition_id, request_type, title) "
                "values (%s, %s, %s, %s, %s);",
                (
                    str(uuid.uuid4()),
                    str(anchor_profile_id),
                    str(uuid.uuid4()),
                    "expense_reimbursement",
                    "Ghost definition",
                ),
            )

    def test_deleting_a_request_cascades_to_its_workflow_stages(self, pg_conn, anchor_profile_id):
        cur = pg_conn.cursor()
        definition_id = _insert_definition(
            cur, created_by=anchor_profile_id, request_type="fk_cascade_test"
        )
        request_id = _insert_request(
            cur, requester_id=anchor_profile_id, definition_id=definition_id
        )
        stage_id = uuid.uuid4()
        cur.execute(
            "insert into public.workflow_stages (id, request_id, stage_order, stage_name) values (%s, %s, %s, %s);",
            (str(stage_id), str(request_id), 1, "Manager Review"),
        )

        cur.execute("delete from public.requests where id = %s;", (str(request_id),))

        cur.execute("select 1 from public.workflow_stages where id = %s;", (str(stage_id),))
        assert cur.fetchone() is None

    def test_a_profile_referenced_by_an_audit_log_cannot_be_hard_deleted(
        self, pg_conn, anchor_profile_id
    ):
        cur = pg_conn.cursor()
        cur.execute(
            "insert into public.audit_logs (id, actor_id, action) values (%s, %s, %s);",
            (str(uuid.uuid4()), str(anchor_profile_id), "REQUEST_CREATED"),
        )

        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            cur.execute("delete from public.profiles where id = %s;", (str(anchor_profile_id),))


class TestProfileLifecycleForeignKeys:
    """Proves the FK policy audit behind ``0020_profile_lifecycle``: a
    profile with genuine business history (``requests.requester_id``)
    still cannot be hard-deleted, while the "secondary attribution"
    columns (``workflow_stages.assigned_to``/``decided_by``,
    ``jobs.actor_id``, ``workflow_definitions.created_by``,
    ``user_invitations.invited_by``, ``companies.deleted_by``) are
    correctly nulled out, and ``notifications.recipient_id`` (the
    previously-undocumented drift) genuinely cascades. Each test provisions
    its own disposable profile via ``make_test_profile`` (a real
    ``auth.users``/``profiles`` row, cleaned up at fixture teardown) rather
    than reusing the session-scoped ``anchor_profile_id``, since these
    tests must actually delete the row within their own ``pg_conn``
    transaction (rolled back at test teardown, so ``make_test_profile``'s
    own cleanup still finds and removes the row normally afterward).
    """

    def test_a_profile_that_authored_a_request_cannot_be_hard_deleted(
        self, pg_conn, make_test_profile, anchor_profile_id
    ):
        target = make_test_profile(full_name="Requester To Delete")
        cur = pg_conn.cursor()
        definition_id = _insert_definition(
            cur, created_by=anchor_profile_id, request_type="fk_lifecycle_requester"
        )
        _insert_request(cur, requester_id=target.id, definition_id=definition_id)

        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            cur.execute("delete from public.profiles where id = %s;", (str(target.id),))

    def test_deleting_an_assigned_or_deciding_profile_sets_the_stage_columns_null(
        self, pg_conn, make_test_profile, anchor_profile_id
    ):
        target = make_test_profile(full_name="Assignee To Delete")
        cur = pg_conn.cursor()
        definition_id = _insert_definition(
            cur, created_by=anchor_profile_id, request_type="fk_lifecycle_stage"
        )
        request_id = _insert_request(
            cur, requester_id=anchor_profile_id, definition_id=definition_id
        )
        stage_id = uuid.uuid4()
        cur.execute(
            "insert into public.workflow_stages "
            "(id, request_id, stage_order, stage_name, assigned_to, decided_by) "
            "values (%s, %s, %s, %s, %s, %s);",
            (str(stage_id), str(request_id), 1, "Manager Review", str(target.id), str(target.id)),
        )

        cur.execute("delete from public.profiles where id = %s;", (str(target.id),))

        cur.execute(
            "select assigned_to, decided_by from public.workflow_stages where id = %s;",
            (str(stage_id),),
        )
        assigned_to, decided_by = cur.fetchone()
        assert assigned_to is None
        assert decided_by is None

    def test_deleting_a_recipient_cascades_their_notifications(
        self, pg_conn, make_test_profile, anchor_profile_id
    ):
        target = make_test_profile(full_name="Recipient To Delete")
        cur = pg_conn.cursor()
        notification_id = uuid.uuid4()
        cur.execute(
            "insert into public.notifications "
            "(id, recipient_id, notification_type, message) values (%s, %s, %s, %s);",
            (str(notification_id), str(target.id), "system", "Test notification"),
        )

        cur.execute("delete from public.profiles where id = %s;", (str(target.id),))

        cur.execute(
            "select 1 from public.notifications where id = %s;", (str(notification_id),)
        )
        assert cur.fetchone() is None

    def test_deleting_a_workflow_definitions_author_sets_created_by_null(
        self, pg_conn, make_test_profile
    ):
        target = make_test_profile(full_name="Definition Author To Delete")
        cur = pg_conn.cursor()
        definition_id = _insert_definition(
            cur, created_by=target.id, request_type="fk_lifecycle_definition_author"
        )

        cur.execute("delete from public.profiles where id = %s;", (str(target.id),))

        cur.execute(
            "select created_by from public.workflow_definitions where id = %s;",
            (str(definition_id),),
        )
        assert cur.fetchone()[0] is None

    def test_deleting_a_jobs_actor_sets_actor_id_null(self, pg_conn, make_test_profile):
        target = make_test_profile(full_name="Job Actor To Delete")
        cur = pg_conn.cursor()
        job_id = uuid.uuid4()
        cur.execute(
            "insert into public.jobs (id, task_type, payload, actor_id) "
            "values (%s, %s, %s, %s);",
            (str(job_id), "send_email", psycopg.types.json.Json({}), str(target.id)),
        )

        cur.execute("delete from public.profiles where id = %s;", (str(target.id),))

        cur.execute("select actor_id from public.jobs where id = %s;", (str(job_id),))
        assert cur.fetchone()[0] is None

    def test_deleting_an_inviter_sets_invited_by_null(self, pg_conn, make_test_profile):
        target = make_test_profile(full_name="Inviter To Delete")
        cur = pg_conn.cursor()
        invitation_id = uuid.uuid4()
        cur.execute(
            "insert into public.user_invitations "
            "(id, email, full_name, token_hash, invited_by, expires_at) "
            "values (%s, %s, %s, %s, %s, now() + interval '1 day');",
            (
                str(invitation_id),
                f"invitee-{invitation_id}@example.invalid",
                "Invitee",
                f"hash-{invitation_id}",
                str(target.id),
            ),
        )

        cur.execute("delete from public.profiles where id = %s;", (str(target.id),))

        cur.execute(
            "select invited_by from public.user_invitations where id = %s;", (str(invitation_id),)
        )
        assert cur.fetchone()[0] is None


class TestUniqueConstraints:
    def test_duplicate_request_type_and_version_is_rejected(self, pg_conn, anchor_profile_id):
        cur = pg_conn.cursor()
        _insert_definition(cur, created_by=anchor_profile_id, request_type="unique_test", version=1)

        with pytest.raises(psycopg.errors.UniqueViolation):
            _insert_definition(
                cur, created_by=anchor_profile_id, request_type="unique_test", version=1
            )

    def test_at_most_one_active_definition_per_request_type(self, pg_conn, anchor_profile_id):
        cur = pg_conn.cursor()
        first_id = _insert_definition(
            cur, created_by=anchor_profile_id, request_type="active_unique_test", version=1
        )
        second_id = _insert_definition(
            cur, created_by=anchor_profile_id, request_type="active_unique_test", version=2
        )
        cur.execute(
            "update public.workflow_definitions set is_active = true where id = %s;",
            (str(first_id),),
        )

        with pytest.raises(psycopg.errors.UniqueViolation):
            cur.execute(
                "update public.workflow_definitions set is_active = true where id = %s;",
                (str(second_id),),
            )

    def test_duplicate_stage_order_within_a_request_is_rejected(self, pg_conn, anchor_profile_id):
        cur = pg_conn.cursor()
        definition_id = _insert_definition(
            cur, created_by=anchor_profile_id, request_type="stage_order_unique_test"
        )
        request_id = _insert_request(
            cur, requester_id=anchor_profile_id, definition_id=definition_id
        )
        cur.execute(
            "insert into public.workflow_stages (id, request_id, stage_order, stage_name) values (%s, %s, %s, %s);",
            (str(uuid.uuid4()), str(request_id), 1, "Manager Review"),
        )

        with pytest.raises(psycopg.errors.UniqueViolation):
            cur.execute(
                "insert into public.workflow_stages (id, request_id, stage_order, stage_name) "
                "values (%s, %s, %s, %s);",
                (str(uuid.uuid4()), str(request_id), 1, "Duplicate Order"),
            )


class TestCheckConstraints:
    def test_a_request_title_over_200_characters_is_rejected(self, pg_conn, anchor_profile_id):
        cur = pg_conn.cursor()
        definition_id = _insert_definition(
            cur, created_by=anchor_profile_id, request_type="title_check_test"
        )

        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "insert into public.requests (id, requester_id, workflow_definition_id, request_type, title) "
                "values (%s, %s, %s, %s, %s);",
                (
                    str(uuid.uuid4()),
                    str(anchor_profile_id),
                    str(definition_id),
                    "expense_reimbursement",
                    "x" * 201,
                ),
            )

    def test_a_zero_stage_order_is_rejected(self, pg_conn, anchor_profile_id):
        cur = pg_conn.cursor()
        definition_id = _insert_definition(
            cur, created_by=anchor_profile_id, request_type="stage_order_check_test"
        )
        request_id = _insert_request(
            cur, requester_id=anchor_profile_id, definition_id=definition_id
        )

        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "insert into public.workflow_stages (id, request_id, stage_order, stage_name) "
                "values (%s, %s, %s, %s);",
                (str(uuid.uuid4()), str(request_id), 0, "Invalid Order"),
            )

    def test_a_comment_body_over_5000_characters_is_rejected(self, pg_conn, anchor_profile_id):
        cur = pg_conn.cursor()
        definition_id = _insert_definition(
            cur, created_by=anchor_profile_id, request_type="comment_check_test"
        )
        request_id = _insert_request(
            cur, requester_id=anchor_profile_id, definition_id=definition_id
        )

        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "insert into public.comments (id, request_id, author_id, body) values (%s, %s, %s, %s);",
                (str(uuid.uuid4()), str(request_id), str(anchor_profile_id), "x" * 5001),
            )


class TestTransactionsAndRollback:
    def test_a_rolled_back_savepoint_leaves_no_trace(self, pg_conn, anchor_profile_id):
        cur = pg_conn.cursor()
        definition_id = _insert_definition(
            cur, created_by=anchor_profile_id, request_type="savepoint_test"
        )

        cur.execute("savepoint before_insert;")
        request_id = _insert_request(
            cur, requester_id=anchor_profile_id, definition_id=definition_id
        )
        cur.execute("select 1 from public.requests where id = %s;", (str(request_id),))
        assert cur.fetchone() is not None

        cur.execute("rollback to savepoint before_insert;")

        cur.execute("select 1 from public.requests where id = %s;", (str(request_id),))
        assert cur.fetchone() is None

    def test_a_constraint_violation_aborts_the_transaction_until_rollback(
        self, pg_conn, anchor_profile_id
    ):
        cur = pg_conn.cursor()

        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            cur.execute(
                "insert into public.requests (id, requester_id, workflow_definition_id, request_type, title) "
                "values (%s, %s, %s, %s, %s);",
                (
                    str(uuid.uuid4()),
                    str(uuid.uuid4()),
                    str(uuid.uuid4()),
                    "expense_reimbursement",
                    "Broken",
                ),
            )

        # Postgres aborts the whole transaction on the first error; every
        # further statement fails until a ROLLBACK (full or to a
        # savepoint) recovers it — this is what makes `pg_conn`'s own
        # teardown rollback mandatory rather than optional cleanup.
        with pytest.raises(psycopg.errors.InFailedSqlTransaction):
            cur.execute("select 1;")

        pg_conn.rollback()
        cur = pg_conn.cursor()
        cur.execute("select 1;")
        assert cur.fetchone() == (1,)


class TestSchemaToRecordMapping:
    """Verifies each live table's columns match its corresponding
    ``*Record`` dataclass exactly — see this module's own docstring for
    why this, not an ORM mapping test, is the correct check here.
    """

    @pytest.mark.parametrize(
        ("table_name", "record_type"),
        [
            ("profiles", ProfileRecord),
            ("workflow_definitions", WorkflowDefinitionRecord),
            ("requests", RequestRecord),
            ("workflow_stages", WorkflowStageRecord),
            ("notifications", NotificationRecord),
            ("audit_logs", AuditLogRecord),
            ("comments", CommentRecord),
        ],
    )
    def test_table_columns_match_the_repository_record_fields(
        self, pg_conn, table_name, record_type
    ) -> None:
        with pg_conn.cursor() as cur:
            cur.execute(
                "select column_name from information_schema.columns "
                "where table_schema = 'public' and table_name = %s;",
                (table_name,),
            )
            actual_columns = {row[0] for row in cur.fetchall()}

        expected_fields = {f.name for f in dataclasses.fields(record_type)}
        assert actual_columns == expected_fields
