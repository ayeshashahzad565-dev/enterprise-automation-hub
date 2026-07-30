# Platform Administration Module

This document describes the platform-admin-only company (tenant) management surface: what exists, the exact enforcement semantics for suspend/delete, the deliberately informational scope of feature flags and license management, and the operator steps required to use any of it (there is no self-service way to become a platform admin).

## 1. Platform admin vs. company admin

`profiles.is_platform_admin` is a boolean, orthogonal to the per-company `role` column (`employee`/`approver`/`admin`). A platform admin's own company-scoped permissions are unaffected by this flag, and it grants nothing beyond the endpoints described here — it is a capability *above* `UserRole.ADMIN`, not a superset of it (`app.auth.authorization.authorize_platform_admin`).

There is no migration, trigger, or admin endpoint that sets this flag — an operator promotes the first (and every subsequent) platform admin directly against the database:

```sql
update public.profiles set is_platform_admin = true where id = '<profile-id>';
```

The frontend's `/platform` section (nav entry, layout guard) becomes visible to that user on their next session refresh.

## 2. Required migration

`0017_platform_admin` adds `companies.deleted_at`/`deleted_by`/`contact_email`/`notes`, and two new tables: `company_licenses` (one row per company) and `feature_flags` (global). Run it before deploying:

```bash
alembic upgrade head
```

Both new tables have RLS enabled and forced with **no grant to `authenticated`** — platform infrastructure state, service-role-only access, matching the `jobs` table's precedent (`0015_jobs`). `companies` itself already had RLS from `0014_companies_rls_and_force_rls`; the new columns need no policy change.

## 3. Company lifecycle

| Action | Endpoint | Effect |
|---|---|---|
| Create | `POST /platform/companies` | New, active company. `slug` is derived server-side; never accepted as input. |
| Update settings | `PATCH /platform/companies/{id}` (`name`/`contact_email`/`notes`) | Metadata only — no access effect. |
| Suspend | `PATCH /platform/companies/{id}` (`is_active: false`) | **Blocks every user in the company on their very next authenticated request** (see Section 4) — not just at next login. |
| Reactivate | `PATCH /platform/companies/{id}` (`is_active: true`) | Restores access immediately. |
| Delete | `DELETE /platform/companies/{id}?expected_version=` | **Soft delete** — sets `deleted_at`/`deleted_by`, blocks access identically to suspension, retains every row the company owns. Excluded from the default company list (`include_deleted=false`). |
| Restore | `POST /platform/companies/{id}/restore` | Reverses a soft-delete. |

A platform admin can never suspend or delete **their own** company — every mutating endpoint above rejects that with `422 VALIDATION_ERROR` (`CompanyService`'s self-lockout guard). This is checked by comparing the target `company_id` to the caller's own `identity.company_id`, so it applies even if the acting platform admin has no company-scoped `admin` role there.

Every mutation above writes an audit entry (`COMPANY_CREATED`/`COMPANY_SUSPENDED`/`COMPANY_REACTIVATED`/`COMPANY_DELETED`/`COMPANY_RESTORED`/`COMPANY_SETTINGS_UPDATED`) — a real gap this module closes, since `CompanyService` previously wrote none at all. `COMPANY_CREATED` is recorded with no `company_id` (a genuinely platform-level event, matching `audit_logs.company_id`'s existing "platform-level event" convention, e.g. `NULL`); every other action records the affected company's id.

## 4. How suspension/deletion is actually enforced

`app.auth.supabase_verifier.SupabaseTokenVerifier.resolve_claims` — the same place a bearer token's `profiles` row is already resolved on every request (this verifier makes a fresh Supabase + database call per call; there is no server-side session cache to go stale) — now also fetches the caller's company and rejects the request (`CompanyAccessRevokedError`, mapped to `401 AUTHENTICATION_REQUIRED`) if it is suspended or soft-deleted. This means:

- Enforcement is immediate: a user with an already-issued, otherwise-valid access token is rejected on their *next* API call after suspension, not merely at their next fresh login.
- **Explicitly out of scope for this baseline**: scheduled jobs (`EscalationJob`/`ReminderJob`) are not modified to skip a suspended company's data — they may still process a suspended tenant's stages/reminders in the background. Suspension's enforcement point is authentication, not the Scheduler.

## 5. License management (informational only)

`GET/PATCH /platform/companies/{id}/license` manages a `plan_tier` (free-text, e.g. `"free"`/`"pro"`/`"enterprise"` — no billing system exists to define a canonical set), `seat_limit`, `expires_at`, and `notes`. The response's `seats_used` (the company's real user count) and `is_expired` (whether `expires_at` has passed) are computed at read time for the UI to display.

**Nothing in this codebase enforces `seat_limit` or `expires_at` against anything** — no invitation is blocked for exceeding a seat limit, no login is blocked for an expired license. This is a deliberate scope decision: the license record is the intended source of truth for a *future* enforcement pass, not a gate today.

A known, disclosed limitation: `seat_limit`/`expires_at` cannot be explicitly cleared back to "unlimited"/"no expiry" via the update endpoint once set (`plan_tier`/`notes` can, via an empty string) — acceptable given the feature's informational scope.

## 6. Feature flags (informational only)

`GET/POST /platform/feature-flags`, `PATCH /platform/feature-flags/{key}` manage a small, global (not per-tenant) set of boolean flags with a description. Like licenses, **nothing in the application reads or enforces these flags yet** — they exist so platform admins have one authoritative place to define and toggle flags ahead of any future feature-gating work.

## 7. Platform statistics and health

`GET /platform/stats` aggregates across every tenant (active/total company counts, total users, total requests, a 30-day daily request-volume trend, active workflow-definition count, total attachment storage in bytes) — the one deliberate exception to this codebase's usual "every aggregate is scoped to one `company_id`" rule (`app.database.repositories.platform_stats_repository.PlatformStatsRepository`), enforced only at the Application Layer (the router calls `authorize_platform_admin` before touching it).

`GET /platform/health` reuses `app.api.routers.health.build_readiness_body` (the same logic backing `/health/ready`) plus dead-letter-by-queue counts from the job system, giving one consolidated, platform-admin-gated view rather than a second health-check implementation.

## 8. Platform-wide audit history and activity timeline

`GET /platform/audit-log` is a new `AuditRepository.list_platform_wide` method — distinct from the pre-existing `list_all` (which hard-requires a single `company_id`, scoping "organization-wide" to one tenant). When called with no `company_id` filter it spans every tenant; passing one narrows to a single company's history. The same endpoint backs both the full, filterable Audit History page and the Platform dashboard's compact recent-activity timeline (last ~15 entries, unfiltered) — one data source, two presentations, no duplicated query logic.

## 9. Explicitly out of scope for this baseline

- **User impersonation** — considered and deliberately deferred; its session/audit/security surface warrants its own dedicated review rather than being folded in here.
- **Feature flag / license enforcement** — see Sections 5–6.
- **Background-job awareness of suspended tenants** — see Section 4.
- **Per-tenant feature flag overrides** — flags are global only in this baseline.
