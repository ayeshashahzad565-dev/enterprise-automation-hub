# Tenant Isolation Architecture

## Summary

Every repository in `app/database/repositories/` used to connect through
Supabase's **service-role** key, which carries Postgres `BYPASSRLS`. The
Row-Level Security policies written across migrations `0003`, `0011`, and
`0014` are correct, but a service-role connection ignores them entirely —
tenant isolation ran 100% on hand-written `company_id` filters in
application code, with no database-level backstop. One omitted filter, in
any repository, would have been a silent cross-tenant data leak with
nothing to catch it.

This document describes the **dual-client architecture** that replaced
that single-mechanism design: a verified subset of repositories now run
every query under the caller's own access token, so Postgres RLS is a real,
enforced boundary for them — and the repositories where that isn't safe
today keep the service-role client, but with mechanical, CI-enforced
scoping safeguards instead of relying on convention.

## How the per-request client works

`SupabaseClientFactory.create_user_scoped_client(settings, access_token)`
(`app/database/client.py`) builds an anon-key client and attaches the
caller's own already-verified bearer token to it
(`client.postgrest.auth(access_token)`) — Supabase's own documented
pattern for a server-side caller that wants RLS enforced instead of
bypassed. A fresh client is built per call; the underlying `.auth(...)`
call mutates headers in place, so reusing one instance across concurrent
callers would let one request's identity leak into another's.

`app.api.dependencies.bind_tenant_database_client` is an **async
generator** FastAPI dependency (`async def ... yield`) attached to every
authenticated router via `app.api.main`'s `_rate_limited` dependency list
(the same list `enforce_rate_limit` already rides on). It builds this
client for the current caller and binds it to a module-private
`contextvars.ContextVar` in `app.database.repositories.base_repository`
for the duration of the request.

It must be an async generator, not a plain `def`, because ~114 of this
API's 116 route handlers are sync `def` functions, which FastAPI/Starlette
dispatch through a thread pool by *copying* the current
`contextvars.Context` — a `.set()` made inside that copy never propagates
back out. An async generator dependency runs directly on the request's own
event-loop task, so the bind happens before any later copy is taken, and
every later copy (whether for a sync dependency or the endpoint itself)
already contains it. `tests/unit/test_base_repository_client_resolution.py`
proves both halves of this against the real `anyio.to_thread.run_sync`
mechanism Starlette uses, not a hand-rolled simulation.

If constructing the client fails (in production, this should be
unreachable — by the time this dependency runs, `get_current_identity`
has already made a real, successful Supabase call with the same token),
the dependency logs an error and simply doesn't bind anything, rather than
failing the request. Every affected repository already falls back to its
own constructor-injected default client when nothing is bound — the same
behavior every repository had before this mechanism existed.

## `BaseRepository`'s role

Every repository's constructor now takes a **required** keyword argument,
`always_use_injected_client: bool` — required so a new repository must
make a conscious choice, never silently inherit one:

- **`True`**: this repository's queries always run on the client injected
  at construction (today, the shared service-role client), regardless of
  any per-request tenant client. Used where this table's RLS policy
  doesn't (yet) match how the service layer actually reads or writes it.
- **`False`**: this repository resolves the per-request tenant-scoped
  client when one is bound, falling back to its injected default
  otherwise (the Scheduler and background jobs never bind one — there is
  no request, so there is no caller to scope to — so they transparently
  keep working exactly as before).

This is a property (`BaseRepository._client`), not a stored attribute, so
none of the ~68 existing query call sites across every concrete repository
needed to change — they all already went through `self._client.table(...)`
via `_query()`/`_select()`.

## Per-table classification

Verified against each table's actual RLS policy *and* how the service
layer actually reads/writes it — not assumed:

| Repository | Mode | Why |
|---|---|---|
| `CommentRepository` | RLS-enforced | Insert policy requires `author_id = auth.uid()`; matches how comments are written. |
| `AttachmentRepository` | RLS-enforced | Same shape. (The Supabase Storage *bucket* itself is a separate policy mechanism, untouched by this change.) |
| `NotificationPreferenceRepository` | RLS-enforced | Every policy is `user_id = auth.uid()` — purely self-owned data. |
| `SavedFilterRepository` | RLS-enforced | Same — self-owned data. |
| `SearchHistoryRepository` | RLS-enforced | Same — self-owned data. |
| `WorkflowDefinitionRepository` | RLS-enforced | Writes are admin-only, matching the policy; reads are company-scoped. |
| `RequestRepository` | Service-role | The approval flow updates a request's stage as the *approver*, not the requester — the update policy only allows requester-or-admin. |
| `WorkflowStageRepository` / `ApprovalRepository` | Service-role | `workflow_stages` has **no INSERT grant** for `authenticated` at all; stage creation and decisions go through these classes. |
| `NotificationRepository` | Service-role | No INSERT grant, and inserts are inherently cross-actor (the system notifies user B about user A's action). |
| `AuditRepository` | Service-role | No INSERT grant at all, by design — the audit trail is system-written. |
| `InvitationRepository` | Service-role | Admin-only policy; the accept-invitation flow also runs *before* a profile/JWT exists. |
| `CompanyRepository` / `CompanyLicenseRepository` / `FeatureFlagRepository` / `PlatformStatsRepository` | Service-role | Legitimately cross-tenant, platform-admin-only operations. |
| `ProfileRepository` | Service-role | RLS would support same-company reads, but this repository also backs cross-company platform-admin lookups and the auth-resolution path itself (which is what establishes company membership in the first place — a chicken-and-egg case). |
| `JobRepository` | Service-role | System/background job bookkeeping, not a caller-scoped resource. |

## Defense-in-depth for the repositories that stay on service-role

Since most of the surface area stays on service-role, this is the primary
lever protecting it, not RLS:

1. **`BaseRepository._scoped_query(company_id=...)`** chains
   `.eq("company_id", ...)` immediately, before any other filter — used by
   every company-wide listing/search entry point on `RequestRepository`,
   `WorkflowStageRepository`, `ApprovalRepository`, `AuditRepository`, and
   `InvitationRepository`. This makes omitting the tenant filter a
   signature-level impossibility at these call sites, not a convention a
   future edit could silently drop.
2. The few genuinely cross-tenant methods (the Scheduler's organization-
   wide escalation sweep, the platform-admin audit view) are explicitly
   marked with a `# tenant-scope-exempt: <reason>` comment rather than
   silently omitted.
3. `tests/unit/test_tenant_scoping_enforcement.py` runs three checks as
   part of the normal `pytest` suite (already gating CI in `ci.yml` — no
   separate job was needed):
   - every concrete repository declares `always_use_injected_client`
     explicitly, as a required, keyword-only, no-default argument;
   - every authenticated route's resolved FastAPI dependency tree includes
     `bind_tenant_database_client` whenever it includes
     `get_current_identity`;
   - every company-wide list/search method named above actually calls
     `_scoped_query`, and every deliberately cross-tenant method carries
     its exemption comment.

## Adding a new repository or table

1. Read the table's actual RLS policies (`app/database/migrations/versions/`)
   and check how the service layer will read/write it — cross-actor writes
   or a missing grant mean it must stay on the service-role client.
2. Pass `always_use_injected_client` explicitly in both the repository's
   own `__init__` and its construction call in `app/bootstrap.py` — there
   is no default, so this cannot be skipped.
3. If it stays on the service-role client and has a `company_id` column,
   route its company-wide listing methods through `self._scoped_query(...)`
   instead of a bare `.eq("company_id", ...)`, and add it to
   `test_tenant_scoping_enforcement.py`'s parametrized cases.

## What this pass didn't do (follow-ups, not silently dropped)

- ~~A live-Postgres integration test proving RLS actually blocks a
  cross-tenant read under a real user JWT~~ — done: `tests/integration`
  now runs in CI (`.github/workflows/integration.yml`) against a real
  local Supabase CLI stack, and `tests/integration/conftest.py` gained a
  `make_authenticated_user` fixture (`auth.sign_in_with_password` plus
  this document's `create_user_scoped_client`) that
  `tests/integration/test_rls_enforcement.py` uses to prove the
  `NotificationPreferenceRepository` policies actually block a real
  signed-in user from reading or writing another user's row. The same
  fixture applies equally to the other RLS-enforced repositories in the
  table above (Comment, Attachment, SavedFilter, SearchHistory,
  WorkflowDefinition) — only `NotificationPreferenceRepository` has a
  test written against it so far, since it needed no parent
  request/workflow setup to exercise; extending this to the others is a
  copy of the same pattern, not a new one.
- **Splitting `workflow_stages`'s missing INSERT grant / `notifications`'
  cross-actor inserts / `audit_logs`' write-once design** into RLS
  policies that could support flipping those tables too. Each is a real
  schema/policy change, not a wiring change, and wasn't made as a side
  effect of this pass.
