"""Auto-provision a profiles row when a new auth.users row is created.

Implements the business rule documented directly in
``app/database/repositories/user_repository.py``'s
``ProfileRepository.create_profile`` docstring: "In normal production
operation this row is created automatically by a Supabase trigger the
first time a user authenticates." Without this trigger, every sign-in
(and every signup/invite/recovery callback, per ``app.py``'s
``SupabaseAuthGateway._build_auth_result``) fails with "Your account is
not fully provisioned" the moment ``ProfileRepository.get_by_id`` finds
no matching row.

The function reads two optional keys out of ``auth.users.raw_user_meta_data``:

- ``full_name`` — falls back to the user's email if absent.
- ``role`` — falls back to ``'employee'`` if absent or not a valid
  ``user_role`` value. Lets ``scripts/seed_demo_data.py`` provision an
  admin directly via ``auth.admin.create_user(user_metadata={"role": "admin", ...})``
  without a second update call.

``on conflict (id) do nothing`` makes the insert idempotent, since
``ProfileRepository.create_profile`` (used by test fixtures per that
method's own docstring) may also insert a row for a user this trigger
already provisioned.

Revision ID: 0002_auth_profile_trigger
Revises: 0001_initial_schema
Create Date: 2026-07-14
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002_auth_profile_trigger"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        create function public.handle_new_user()
        returns trigger
        language plpgsql
        security definer
        set search_path = public
        as $$
        declare
            resolved_role public.user_role;
        begin
            begin
                resolved_role := (new.raw_user_meta_data->>'role')::public.user_role;
            exception when invalid_text_representation then
                resolved_role := 'employee';
            end;
            if resolved_role is null then
                resolved_role := 'employee';
            end if;

            insert into public.profiles (id, full_name, role)
            values (
                new.id,
                coalesce(new.raw_user_meta_data->>'full_name', new.email),
                resolved_role
            )
            on conflict (id) do nothing;

            return new;
        end;
        $$;
        """
    )
    op.execute(
        "create trigger on_auth_user_created "
        "after insert on auth.users "
        "for each row execute function public.handle_new_user();"
    )


def downgrade() -> None:
    op.execute("drop trigger if exists on_auth_user_created on auth.users;")
    op.execute("drop function if exists public.handle_new_user();")
