# app/database/migrations

This directory is the designated location for this package's database
migration history, managed through **Alembic**, per the Database Schema
Design Document (DSD Section 15) and the Deployment Guide (DG Section
11).

## Scope of This Directory

Per the DSD and Deployment Guide, Alembic is used strictly as a
development-time and deployment-time schema-versioning tool — it has no
runtime presence anywhere in `app/database`'s own code (`client.py`,
`exceptions.py`, or any module under `repositories/`). No repository in
this package imports Alembic, and no migration script in this directory
should import anything from `app.database.repositories`, since a
migration operates on raw schema, not through the Repository Layer's
domain-shaped interface.

This directory holds:

- `env.py` — Alembic's environment configuration, wiring the migration
  runner to the target database connection (sourced from the
  Configuration Loader's `DATABASE_URL`, per the Deployment Guide's
  environment variable table, DG Section 8).
- `script.py.mako` — the template new migration files are generated from.
- `versions/` — the ordered set of individual migration scripts, one per
  schema change, forming the project's complete, append-only schema
  history.

This directory now holds the initial revision history:

- `0001_initial_schema` — every native enum type, table, index, and
  constraint (`profiles`, `workflow_definitions`, `requests`,
  `workflow_stages`, `notifications`, `audit_logs`), plus the
  `updated_at`-maintenance trigger.
- `0002_auth_profile_trigger` — the `on_auth_user_created` trigger that
  auto-provisions a `profiles` row for each new `auth.users` row.
- `0003_row_level_security` — grants and RLS policies for every table.

Since no SQLAlchemy ORM models exist anywhere in this project (the
fixed technology stack is Supabase/PostgREST, not an ORM), every
revision here is hand-authored raw SQL via `op.execute(...)`, not
generated with `alembic revision --autogenerate` — `env.py` sets
`target_metadata = None` accordingly. Future revisions should be created
with a plain `alembic revision -m "..."` and written the same way.

## Migration Principles (per DSD Section 15 and DG Section 11)

1. **Version-controlled.** Every migration script is committed to source
   control alongside the application code it corresponds to. The
   migration history is the single source of truth for how the schema
   reached its current shape.

2. **Forward-only.** A migration is never edited or deleted once merged.
   A correction to an already-applied migration is expressed as a new,
   subsequent migration — mirroring the same append-only philosophy
   already applied to the `audit_logs` table (DSD Section 6).

3. **Backward-compatible during rollout.** Per Deployment Guide Section
   11.3, a migration that a new application release depends on is
   authored as an additive "expand" step, deployed ahead of the
   application code that depends on it. Any corresponding "contract" step
   (e.g. dropping a column no longer used) is deployed only in a later
   release, once every running instance is confirmed on the new code —
   this is what makes EAH's rolling, zero-downtime deployment strategy
   (DG Section 22) safe.

4. **Tested before production.** Per DSD Section 15, every migration is
   applied and verified against a disposable test database — exercising
   both the upgrade path and, where authored, the downgrade path — before
   being applied to staging or production. The project's CI pipeline (per
   the Testing Strategy Document, Section 13.3) applies the full
   migration history from empty to head on every commit as a continuous
   verification of this property.

5. **Applied before application code starts.** Per Deployment Guide
   Section 11.2, migrations are always applied to the target database
   before the corresponding new application code begins serving traffic
   — never concurrently with, and never after.

## Running Migrations

```bash
# Apply every pending migration up to the latest revision
alembic upgrade head

# Generate a new migration from the current models (once models exist)
alembic revision --autogenerate -m "add workflow_definitions table"

# Roll forward to a specific revision
alembic upgrade <revision_id>

# Roll back to a specific revision (only where a tested downgrade path exists,
# per Deployment Guide Section 18.2 — never used as a substitute for verifying
# the resulting schema matches what the corresponding application version expects)
alembic downgrade <revision_id>
```

## Relationship to `app/database`

The tables, columns, constraints, and enum types this migration history
will define are already fully specified in the Database Schema Design
Document (DSD Sections 3–4) and referenced directly by the repositories in
`app/database/repositories/` — every column name, enum value, and
constraint a repository in this package reads or writes corresponds
exactly to what the eventual migration history in this directory will
create. No repository in this package assumes a schema shape beyond what
the DSD specifies.