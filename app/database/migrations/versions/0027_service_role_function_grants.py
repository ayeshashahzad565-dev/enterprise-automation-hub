"""Grant the service_role execute on the analytics aggregation functions.

``0022`` ends by revoking ``execute`` on its four analytics functions from
``public``, so that an anon/authenticated caller cannot reach them through
PostgREST's automatic RPC exposure. That intent is right and is preserved
here. What it never did was grant ``execute`` to ``service_role``, which is
the role ``AnalyticsRepository`` actually connects as, leaving the
functions callable by nobody but their owner:

    postgrest.exceptions.APIError:
    {'message': 'permission denied for function
     analytics_count_requests_by_status'}

This is the same gap ``0026`` closed for tables, in its function form, and
it hid for the same reason: a hosted Supabase project grants ``execute`` on
new functions to ``service_role`` through platform-level ``ALTER DEFAULT
PRIVILEGES`` at project creation. A direct grant of that kind survives a
later ``revoke ... from public``, since the two target different grantees —
so on a hosted project the analytics endpoints work, while a database built
from these migrations alone rejects every one of them.

Only ``service_role`` is granted. ``anon`` and ``authenticated`` remain
without ``execute``, which is exactly what ``0022``'s revoke set out to
achieve. The ``0011``/``0025`` RLS helper functions are untouched: they
never revoked from ``public``, so they keep the default ``execute`` that
the policies calling them rely on.

Revision ID: 0027_service_role_function_grants
Revises: 0026_service_role_table_grants
Create Date: 2026-08-23
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0027_service_role_function_grants"
down_revision: str | None = "0026_service_role_table_grants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Kept identical to ``0022``'s own ``_FUNCTIONS`` tuple, argument types
#: included — ``grant execute on function`` needs the full signature to
#: identify an overload.
_FUNCTIONS: tuple[str, ...] = (
    "analytics_count_requests_by_status(uuid, text, text, timestamptz, timestamptz)",
    "analytics_count_requests_by_type(uuid, text, timestamptz, timestamptz)",
    "analytics_count_requests_by_department(uuid, text, timestamptz, timestamptz)",
    "analytics_approval_throughput(uuid, text, timestamptz, timestamptz)",
)


def upgrade() -> None:
    for signature in _FUNCTIONS:
        op.execute(f"grant execute on function public.{signature} to service_role;")

    # Mirrors 0026's equivalent for tables, and reproduces what a hosted
    # project already does: a future function is then reachable by the
    # service-role client without a follow-up migration, and a `revoke
    # ... from public` alongside it still locks out anon/authenticated.
    op.execute("alter default privileges in schema public grant execute on functions to service_role;")


def downgrade() -> None:
    op.execute(
        "alter default privileges in schema public revoke execute on functions from service_role;"
    )

    for signature in reversed(_FUNCTIONS):
        op.execute(f"revoke execute on function public.{signature} from service_role;")
