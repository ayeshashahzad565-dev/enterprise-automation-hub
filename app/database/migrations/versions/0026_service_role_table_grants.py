"""Grant the service_role table privileges this schema always assumed.

Every ``grant`` in this schema's history targets ``authenticated`` only.
``service_role`` — the role the application's privileged client connects
as (``app/database/client.py``), and the one every background job, seed
script, and service-role repository call runs under — was never granted
anything.

That went unnoticed because a hosted Supabase project provisions those
privileges outside of migrations, via platform-level ``ALTER DEFAULT
PRIVILEGES`` applied when the project is created. A database built purely
from this repository's migrations does not get them, so every
service-role query failed:

    postgrest.exceptions.APIError: {'message': 'permission denied for
    table companies', 'code': '42501'}

which is what broke the E2E seed step and the bulk of the integration
suite against a local ``supabase start`` stack. Anyone provisioning their
own Postgres from these migrations hit exactly the same wall.

Relying on the platform to supply privileges the schema depends on also
left the two able to drift apart silently. Granting explicitly makes the
schema self-contained and portable, and matches ``0003``'s stated
posture that access is granted deliberately per table rather than
inherited by default.

``audit_logs`` deliberately receives only ``select, insert``. That table
is append-only by design, and the mechanism enforcing it is precisely the
absence of an ``update``/``delete`` grant (``0003``: "a bare table with
no grant would still deny all access"). Granting them here would quietly
dismantle the immutability guarantee the audit trail is built on.

RLS is unaffected. ``service_role`` holds ``BYPASSRLS``, so the policies
added by ``0003``/``0011``/``0014``/``0016``/``0019``/``0025`` continue to
govern ``authenticated`` exactly as before; this migration changes only
the table-level privileges that must be present before RLS is ever
consulted.

Revision ID: 0026_service_role_table_grants
Revises: 0025_fix_requests_workflow_stages_rls_recursion
Create Date: 2026-08-21
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0026_service_role_table_grants"
down_revision: str | None = "0025_fix_requests_workflow_stages_rls_recursion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Every table this schema creates, across 0001-0019, that the
#: service-role client reads and writes.
_READ_WRITE_TABLES: tuple[str, ...] = (
    "profiles",
    "workflow_definitions",
    "requests",
    "workflow_stages",
    "notifications",
    "comments",
    "attachments",
    "user_invitations",
    "companies",
    "jobs",
    "notification_preferences",
    "company_licenses",
    "feature_flags",
    "saved_filters",
    "search_history",
)

#: Append-only: see this module's docstring.
_APPEND_ONLY_TABLES: tuple[str, ...] = ("audit_logs",)


def upgrade() -> None:
    op.execute("grant usage on schema public to service_role;")

    for table in _READ_WRITE_TABLES:
        op.execute(f"grant select, insert, update, delete on public.{table} to service_role;")

    for table in _APPEND_ONLY_TABLES:
        op.execute(f"grant select, insert on public.{table} to service_role;")

    # Without this, a future migration that adds a table would reintroduce
    # exactly the gap this one closes — the new table would be readable on
    # a hosted project (platform defaults) and denied everywhere else.
    op.execute(
        "alter default privileges in schema public "
        "grant select, insert, update, delete on tables to service_role;"
    )


def downgrade() -> None:
    op.execute(
        "alter default privileges in schema public "
        "revoke select, insert, update, delete on tables from service_role;"
    )

    for table in _APPEND_ONLY_TABLES:
        op.execute(f"revoke select, insert on public.{table} from service_role;")

    for table in _READ_WRITE_TABLES:
        op.execute(f"revoke select, insert, update, delete on public.{table} from service_role;")

    # `usage on schema public` is deliberately not revoked: it is not this
    # migration's to take away. A hosted Supabase project grants it at
    # project creation, and revoking it here would break service-role
    # access to anything outside this schema's own tables.
