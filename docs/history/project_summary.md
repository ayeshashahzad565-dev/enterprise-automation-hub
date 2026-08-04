# Enterprise Automation Hub — Project Summary

**Generated:** 2026-07-19, from direct inspection of the repository (backend `app/`, frontend `frontend/`). Every claim below is sourced from actual code, migrations, config files, or test runs performed at generation time — not from assumption. Where something could not be confirmed, or is incomplete/missing, that is stated explicitly rather than guessed.

---

## 1. Executive Summary

### Purpose
Enterprise Automation Hub (EAH) is a modular-monolith web application for **configurable, multi-stage approval workflows** inside an organization. Employees submit requests (leave, expense reimbursement, purchase orders, access requests, hardware/software requests, travel, contracts, recruitment), each request is routed through a versioned, admin-configurable chain of approval stages, and approvers (or admins) decide each stage until the request reaches a terminal state. The system also provides analytics/reporting, in-app + email notifications, a full audit trail, and a visual workflow designer.

### Current development status
**Actively developed, functionally complete backend + frontend, not yet production-hardened.** The backend is a FastAPI REST API against a Supabase-hosted Postgres database; the frontend is a Next.js 15 / React 19 single-page-app-style client. The project **previously had a Streamlit-based UI**, which has been **fully removed** in the current session (see Section 12). CI covers backend lint/typecheck/test only — the frontend is never built or linted in CI (Section 11). No containerization/deployment pipeline exists (Section 2).

### Major completed features
- Full request lifecycle: create, view, list/search, edit (while pending), withdraw (soft-delete), audit trail.
- Multi-stage configurable workflow engine with three assignment strategies (specific user, department queue, requester's-manager-by-department) and automatic escalation on overdue stages.
- Approval inbox with single and bulk approve/reject, keyboard navigation, saved views.
- Comments (threaded, soft-deletable, admin-moderated) and attachments (versioned replace chain, checksum, virus-scan integration point, signed download URLs) on requests.
- In-app notifications (list, unread count, mark read/all-read, archive/unarchive) with independent email dispatch.
- Two parallel analytics stacks: a narrow one feeding the personal dashboard, and a rich one (`app/analytics/analytics_engine.py`) backing a full `/analytics` page (executive/operational/explorer tabs, department comparison, workload, trend, CSV export).
- Admin area: user directory (role/department edit), read-only permission matrix, department workload view, platform settings viewer, admin operational dashboard.
- Visual workflow designer (React Flow canvas) with version history, diffing, draft autosave, undo/redo, and publish/activate flow.
- Role-based access control (employee / approver / admin) enforced server-side via a small set of pure `rbac.py` predicate functions, backed by Postgres Row-Level Security as defense-in-depth.
- Background jobs (APScheduler): hourly escalation sweep, daily reminder dispatch, 5-minute health-check snapshot.
- A large, realistic enterprise demo dataset (7 departments, ~65-70 users, ~650 requests) seeded this session via `scripts/seed_enterprise_demo.py`.

### Features partially implemented
- **Analytics**: two independent stacks (Section 6/16 detail this — not a bug, but real, unreconciled duplication).
- **Scheduler**: a "Nightly Analytics Aggregation" job is configured (`SCHEDULER_ANALYTICS_INTERVAL_HOURS` env var exists, documented) but **no such job class exists anywhere in `app/scheduler`** — a configured-but-unimplemented feature.
- **Admin → Workflow definition counts**: `admin_dashboard.py`'s `workflow_definition_counts` is hardcoded to check only `expense_reimbursement` — not a true count across all 9 request types, because no cross-type "list every definition" backend method exists.
- **Password hashing utilities** (`app/auth/password.py`, PBKDF2-HMAC-SHA256) exist but have **no call site** — Supabase Auth handles all real credential storage/verification; this is unused, generic infrastructure.
- **Middleware/decorator infrastructure** (`app/auth/decorators.py`'s `require_authentication`/`require_permission_decorator`/`require_role_decorator`) exists but is **not used by any router** — routers call `rbac`/`authorization` functions inline instead.

### Missing features
- No department entity/table — "department" is free text on `profiles`, with no management UI beyond viewing distinct values.
- No password-reset/invite-user flow exposed via the admin API (no such endpoints exist).
- No health endpoint exposing scheduler statistics (`HealthCheckJob.get_latest_snapshot()` exists but is wired to nothing).
- No frontend CI (build/lint never run in GitHub Actions).
- No Docker/containerization or documented deployment pipeline (a `docs/deployment.md` exists as a design document, not a working pipeline — not independently verified in this pass).
- Conditional/branching workflow stages (skip logic) — `StageStatus.SKIPPED` and `RequestStatus.APPROVED` exist as enum values but are documented as unreachable by any current code path (forward-looking placeholders).

---

## 2. Technology Stack

### Frontend
- **Framework**: Next.js **15.5.20** (App Router), React **19.2.4** / React DOM 19.2.4, TypeScript 5.
- **Styling**: Tailwind CSS v4 (via `@tailwindcss/postcss`), `tailwind-merge`, `tw-animate-css`, `class-variance-authority`, `clsx`.
- **Component library**: shadcn/ui-derived primitives (`components.json`: style `base-nova`, base color `neutral`) built on `@base-ui/react` (not Radix directly).
- **Forms**: `react-hook-form` + `zod` + `@hookform/resolvers`.
- **Data/server-state**: `@tanstack/react-query` v5 (+ devtools in dev) — the only "global state" layer; no Redux/Zustand/Jotai.
- **Tables**: `@tanstack/react-table` v8, wrapped in a shared `DataTable` pattern (server-side pagination/filtering, client-side sort).
- **Charts**: `recharts` v3.
- **Visual workflow canvas**: `@xyflow/react` (React Flow) v12 — noted in code comments as the single largest frontend dependency, lazy-loaded (`next/dynamic`, `ssr: false`).
- **Command palette**: `cmdk`.
- **Notifications (toast)**: `sonner`.
- **Theming**: `next-themes`.
- **Icons**: `lucide-react`.
- **Dates**: `date-fns`.
- **Resizable panels**: `react-resizable-panels` (workflow designer split view).
- **Note**: `framer-motion` is **not installed** — no animation library dependency exists beyond CSS/Tailwind and a hand-rolled Canvas 2D engine for the login page's decorative animation.

### Backend
- **Framework**: FastAPI (`>=0.110`), Uvicorn (`[standard]`, `>=0.29`) as ASGI server.
- **Language**: Python `>=3.11` (mypy config pins `3.12` specifically for third-party stub compatibility — see Section 11).
- **Validation**: Pydantic v2 (`>=2.5`).
- **Migrations**: Alembic (`>=1.13`).
- **DB driver**: `psycopg[binary]` (`>=3.1`), used only by Alembic for direct connections; runtime queries go through the Supabase Python SDK's PostgREST client, not raw SQL.
- **Scheduler**: APScheduler (`>=3.10`), `BackgroundScheduler` with `IntervalTrigger`.
- **Config**: `python-dotenv`.
- **File uploads**: `python-multipart`.
- **Dev/test tooling**: pytest + pytest-cov, black, ruff, mypy, httpx (for FastAPI `TestClient`).

### Database
- **Postgres**, hosted on **Supabase** (confirmed live project used throughout this session; also usable as a self-hosted Postgres in principle since Alembic drives schema via a plain `DATABASE_URL`).
- 8 tables (Section 5): `profiles`, `workflow_definitions`, `requests`, `workflow_stages`, `notifications`, `audit_logs`, `comments`, `attachments`.
- Postgres native enums for `user_role`, `request_status`, `stage_status`, `notification_type`.
- Row-Level Security enabled on every table, as **defense-in-depth** — the app's actual runtime queries use the Supabase **service-role** client, which bypasses RLS entirely; RLS is what would protect data if a future direct-from-browser/anon-key client were ever added.
- `pgcrypto` extension for `gen_random_uuid()` (defensive; native in Postgres 13+).

### Authentication
- **Supabase Auth** end to end. No custom session store, no server-side session table.
- Stateless bearer-token model: every API request carries a Supabase JWT, and the backend **re-verifies it against Supabase on every single request** (`client.auth.get_user(token)`) — no token cache, no server-side session.
- Role (`employee`/`approver`/`admin`) is **always resolved from the `profiles` table**, never trusted from the raw JWT.
- Frontend: `@supabase/ssr` browser + server clients; Next.js middleware refreshes/validates the session cookie on every navigation.

### State management
- Frontend: TanStack Query for all server state (60s default `staleTime`, retry: 1); React Context only for auth/theme/tooltip; `localStorage`/`sessionStorage` for small UI preferences (column visibility, saved views, remember-me flag, draft persistence).
- Backend: no in-process caching layer; every read hits Supabase fresh. Scheduler job statistics are the only meaningful in-memory server state, and they're per-process (not shared across instances).

### APIs
- One versioned REST API, prefixed `/api/v1`, documented at `/api/docs` (Swagger) and `/api/redoc`.
- A standard JSON response envelope (`data`/`meta` for single resources, `data`/`pagination`/`meta` for lists, `error`/`meta` for failures) — implemented in `app/utils/response.py` and enforced via centralized exception handlers, never a raw stack trace.

### Libraries
See dependency lists above (Frontend/Backend) — these are the full production dependency sets as declared in `frontend/package.json` and `pyproject.toml`/`requirements.txt` at the time of writing.

### Infrastructure
- No containerization (no `Dockerfile`/`docker-compose.yml` found in the repository).
- No infrastructure-as-code found.
- Local dev: `uvicorn` for the backend, `next dev` for the frontend, both talking to a real (or locally-pointed) Supabase project — there is no fully-offline local Postgres setup documented or verified in this pass.

### Deployment readiness
**Not production-ready as configured.** Concretely:
- CI never builds or lints the frontend (Section 11) — a broken frontend build could merge to `main` undetected.
- No containerized build artifact exists for either service.
- `README.md`'s documented run command (`uvicorn app.api.main:app --reload`) is **stale/incorrect** — the actual app object is a factory function (`create_app`), requiring `--factory` (Section 14/Known Issues).
- Scheduler leader election is a manual operator convention (`SCHEDULER_LEADER=true` on exactly one instance), not enforced by the code — misconfiguration risk in any multi-instance deployment.
- A "Nightly Analytics Aggregation" job is configured via env var but not implemented (Section 1).
- No secrets-management integration beyond plain `.env` files.

---

## 3. Project Structure

Full tree (excluding `.git`, `node_modules`, `.next`, `__pycache__`, `.venv`, and build/cache artifacts like `htmlcov`, `dist`, `.pytest_cache`, `.ruff_cache`, `.mypy_cache`):

```
.
├── .claude/                         # Claude Code session/config metadata (not project source)
├── .github/
│   └── workflows/
│       ├── ci.yml                   # Backend lint (ruff) + typecheck (mypy) + test (pytest) on push/PR to main
│       └── security.yml             # Weekly + on-push pip-audit dependency vulnerability scan
├── .vscode/settings.json
├── CODE_OF_CONDUCT.md
├── CONTRIBUTING.md
├── LICENSE
├── README.md                        # Project overview — contains some stale content, see Section 11/12
├── SECURITY.md
├── alembic.ini                      # Alembic config; sqlalchemy.url resolved from DATABASE_URL at runtime
├── app/                             # === BACKEND (FastAPI) ===
│   ├── analytics/                   # Rich analytics engine (Stack B) — backs the /analytics API
│   │   ├── aggregations.py          # Pure grouping/counting helpers (by department, type, requester, ...)
│   │   ├── analytics_engine.py      # AnalyticsEngine — the AnalyticsProvider implementation
│   │   ├── dto.py                   # Frozen dataclasses: DashboardMetrics, WorkflowMetrics, TrendPoint, ...
│   │   ├── exceptions.py
│   │   ├── interfaces.py            # AnalyticsProvider / ReportingProvider protocols
│   │   ├── metrics.py               # Pure metric-calculation functions (completion_rate, avg latency, ...)
│   │   └── reporting.py             # ReportingEngine — builds narrative AnalyticsSummary DTOs
│   ├── api/
│   │   ├── main.py                  # create_app() factory: middleware stack, router mounting, lifespan
│   │   ├── dependencies.py          # FastAPI Depends() providers — identity, services, repos
│   │   ├── exception_handlers.py    # Central exception → standard JSON envelope mapping
│   │   ├── middleware.py            # RequestID, SecurityHeaders, RequestLogging ASGI middleware
│   │   ├── routers/                 # One file per resource — 17 routers, see Section 6
│   │   └── schemas/                 # Pydantic request/response schemas per resource
│   ├── auth/                        # Authentication & authorization — see Section 9
│   │   ├── authentication.py        # Bearer-token extraction, AuthenticatedIdentity
│   │   ├── authorization.py         # Ownership-based authorize_* functions
│   │   ├── decorators.py            # Framework-agnostic auth decorators (currently unused by routers)
│   │   ├── middleware.py            # AuthenticationMiddleware/AuthorizationMiddleware pipeline abstraction
│   │   ├── password.py              # Generic PBKDF2 hashing utilities (no current call site)
│   │   ├── permissions.py           # ROLE_PERMISSIONS — declarative permission sets per role
│   │   ├── rbac.py                  # Pure can_* predicate functions — the real authorization logic
│   │   └── supabase_verifier.py     # SupabaseTokenVerifier — real per-request Supabase verification
│   ├── bootstrap.py                 # build_application_resources() — the single composition root
│   ├── config/                      # Settings, environment, logging, security config, path constants
│   ├── database/
│   │   ├── client.py                # SupabaseClientFactory — anon/service-role client construction
│   │   ├── migrations/versions/     # 6 Alembic migrations — see Section 5
│   │   └── repositories/            # One repository per table + base_repository.py (pagination, locking)
│   ├── models/                      # Pydantic Domain Layer models — one file per entity + enums.py
│   ├── notifications/               # Templated notification stack (Stack A — currently unwired, see Section 1)
│   ├── scheduler/                   # APScheduler jobs — escalation, reminder, health-check
│   ├── services/                    # Application Layer — orchestrates repos/engine/notifications
│   ├── utils/                       # Cross-cutting helpers: pagination, response envelope, retry, decorators
│   └── workflow/                    # Pure workflow engine — see Section 8
├── assets/                          # demo/, diagrams/, logo/, screenshots/ — static project assets
├── docs/                            # Design documents (requirements, architecture, DB schema, API design,
│                                     #   workflow engine, testing strategy, deployment, design philosophy) —
│                                     #   several still describe the removed Streamlit UI, see Section 12
├── frontend/                        # === FRONTEND (Next.js) ===
│   ├── src/
│   │   ├── app/                     # Next.js App Router — routes, see Section 7
│   │   ├── components/
│   │   │   ├── layout/              # AppShell, Header, Sidebar, nav data, UserMenu, ThemeToggle
│   │   │   ├── patterns/            # Higher-level composed patterns (PageHeader, EmptyState, DataTable, charts/)
│   │   │   └── ui/                  # shadcn-derived primitives (button, dialog, select, table, ...)
│   │   ├── features/                # Feature modules — one folder per domain area, see Section 7
│   │   ├── hooks/                   # App-wide hooks (use-auth-session.ts)
│   │   ├── lib/                     # API client, Supabase clients, query-client config, utils
│   │   ├── providers/               # AuthProvider, QueryProvider, ThemeProvider
│   │   ├── services/                # Thin API-client wrappers, one per resource — 11 files
│   │   ├── types/                   # Shared TypeScript types mirroring backend response shapes
│   │   ├── utils/constants.ts       # Route paths, misc constants
│   │   └── middleware.ts            # Next.js middleware — delegates to Supabase session-refresh/redirect logic
│   ├── package.json
│   ├── tsconfig.json / next.config.ts / eslint.config.mjs / components.json / postcss.config.mjs
│   └── .env.local.example
├── logs/                            # Runtime log output directory
├── pyproject.toml                   # Backend package metadata, deps, tool config (black/ruff/mypy/coverage)
├── pytest.ini                       # pytest config — testpaths, markers, coverage flags
├── requirements.txt                 # Backend production dependency pins
├── scripts/                         # Operational scripts — see Section 14
│   ├── initialize_db.py             # Fresh-migration + optional seed, for a brand-new database
│   ├── reset_database.py            # Full downgrade+upgrade reset (guarded against Staging/Production)
│   ├── seed_demo_data.py            # Minimal single-admin-user + default-workflow bootstrap seed
│   ├── seed_enterprise_demo.py      # Full realistic multi-department demo dataset seeder
│   └── seed_profile_demo_data.py    # Backfills activity for two specific named test accounts
└── tests/                           # See Section 11 for shape/counts
    ├── acceptance/ | fixtures/ | integration/ | performance/ | security/ | unit/
```

**Folder purposes not already covered inline above:**
- **`app/api/schemas/`** — request/response Pydantic shapes distinct from `app/models/` (Domain Layer); schemas are the API contract, models are the persisted/business representation.
- **`app/database/repositories/`** — the only layer allowed to talk to the Supabase client directly; every repository extends `base_repository.py`'s shared pagination/optimistic-locking/exception-translation logic.
- **`assets/`** — static images/diagrams for documentation and the demo dataset; not consumed by either running application.
- **`docs/`** — pre-implementation design documents (requirements/architecture/DB-schema/API-design/workflow-engine/testing-strategy/deployment/design-philosophy). These describe the *original* specification and, per Section 12, several still describe the now-removed Streamlit UI as current.

---

## 4. Architecture

### Overall architecture
A **modular monolith**, not microservices: one FastAPI process serves the entire REST API, backed by one Supabase project (Postgres + Auth + Storage). The frontend is a separate Next.js process/deployment consuming that API over HTTP. Internally, the backend follows a strict layering discipline documented throughout the codebase's own docstrings:

```
API Layer (routers)  →  Application Layer (services)  →  Domain Layer (models) / Workflow Engine (pure logic)
                                    ↓
                          Repository Layer (one per table)
                                    ↓
                          Supabase (Postgres via PostgREST, Auth, Storage)
```

`app/bootstrap.py`'s `build_application_resources()` is the **single composition root** — it constructs every repository, service, the workflow engine, the analytics engines, the notification stack(s), and the scheduler exactly once at process startup, wiring them together and returning one `ApplicationResources` dataclass instance stored on `app.state.resources`. Every FastAPI dependency provider in `app/api/dependencies.py` simply reads an already-built object off that instance — no service/repository is ever constructed per-request.

### Data flow
1. Frontend service function (`src/services/*.ts`) calls `apiClient`, which attaches a fresh Supabase bearer token.
2. Request hits a FastAPI router; `Depends(get_current_identity)` re-verifies the token against Supabase and resolves the caller's role from `profiles`.
3. The router calls exactly one Application Service method, passing the `AuthenticatedIdentity` plus already-validated request data.
4. The service authorizes (via `rbac`/`authorization` functions), orchestrates one or more repository calls and/or the pure `WorkflowEngine`, writes an audit-log entry, and dispatches notifications.
5. Repositories translate to/from Supabase's PostgREST query builder, mapping raw rows to Domain Layer Pydantic models.
6. The service returns a Domain Layer object; the router serializes it into the standard response envelope.

### Authentication flow
See Section 9 for full detail. Summary: Supabase-issued JWT → `SupabaseTokenVerifier.resolve_claims` calls `client.auth.get_user(token)` (real network call, every request) → role resolved from `profiles` (never trusted from the JWT) → `AuthenticatedIdentity` constructed → used for the remainder of that single request only (never cached/persisted).

### Request lifecycle (the core business object, "a request")
1. **Create**: `RequestService.create_request` resolves the active `workflow_definitions` row for the given `request_type`, generates stage 1 via `WorkflowEngine`/`StageGenerator`, persists the request + first stage in one `TransactionContext` (compensation-based, not true multi-statement ACID — see Section 8), writes an audit entry, notifies the resolved assignee.
2. **Decide**: an approver (or eligible role) calls approve/reject; `ApprovalService` authorizes, transitions the stage under optimistic locking, and — on approval — asks `WorkflowEngine` for the next stage (generating and persisting it) or marks the request `COMPLETED` if none remains; on rejection, the request becomes `REJECTED` (terminal).
3. **Escalate**: if a pending stage passes its `escalation_hours` threshold (computed on demand from `stage.created_at`, never persisted), the hourly `EscalationJob` reassigns it to the fallback role (`admin`) via the same `ApprovalService.escalate_stage` path used by the same optimistic-locking machinery a human decision uses.
4. **Withdraw**: the requester (while pending) or an admin (any status) can soft-delete the request (`deleted_at` set) — never hard-deleted.

### API structure
One REST API versioned at `/api/v1`, 17 router files, ~60 endpoints total (exact inventory in Section 6). Every list endpoint supports pagination; most support filtering; a subset (analytics) support CSV export via `?format=csv`. Every response follows the same envelope regardless of endpoint.

### Database interaction
The backend **never writes raw SQL against its own tables at runtime** — all reads/writes go through the Supabase Python SDK's PostgREST-based query builder, encapsulated entirely inside `app/database/repositories/*.py`. Alembic + `psycopg` are used **only** for schema migrations (DDL), not application queries. The service-role client bypasses Row-Level Security; RLS exists as a defense-in-depth boundary for any future caller using the anon key directly.

### Frontend architecture
Next.js App Router with a `(app)` route group sharing one authenticated shell (`AppShell` = `Sidebar` + `Header` + scrollable `main`). Feature-based organization (`src/features/<domain>/{components,hooks,schemas,query-keys.ts}`) rather than type-based — each feature owns its React Query hooks, its Zod schemas, and its presentational components. Server state lives exclusively in TanStack Query; there is no separate client-state store. Role-based route protection exists **only client-side** for `/admin/*` (a `layout.tsx` redirect after `useCurrentUser()` resolves) — the real enforcement is server-side FastAPI 403s; the client-side check is explicitly documented in its own code comment as "for usability, not the real enforcement point."

---

## 5. Database

Full schema, sourced directly from the 6 Alembic migrations (`0001_initial_schema.py` → `0006_notification_archive.py`) and cross-referenced against `app/models/*.py`. **8 tables total.**

### Enum types (native Postgres)
| Enum | Values |
|---|---|
| `user_role` | `employee`, `approver`, `admin` |
| `request_status` | `pending`, `in_review`, `approved` (reserved/unreachable), `rejected`, `completed` |
| `stage_status` | `pending`, `approved`, `rejected`, `skipped` (unreachable — forward-looking) |
| `notification_type` | `assignment`, `reminder`, `escalation`, `decision`, `completion`, `system` |

`AuditAction` and `AttachmentScanStatus` are Domain-Layer-only enums backed by plain `text` columns (with a `check` constraint for the latter), not native Postgres enum types — a deliberate choice documented in code.

### `profiles`
**Purpose**: extends `auth.users` with `full_name`, `role`, `department` — one row per user, auto-created by the `on_auth_user_created` trigger (below).
| Column | Type | Notes |
|---|---|---|
| `id` | uuid | PK, FK → `auth.users(id)` ON DELETE CASCADE |
| `full_name` | text | not null |
| `role` | user_role | not null, default `employee` |
| `department` | text | nullable |
| `version` | integer | not null, default 1, `check > 0` |
| `created_at`/`updated_at` | timestamptz | `updated_at` auto-maintained by trigger |

Index: `(role, department)`. RLS: any authenticated user may `SELECT` all profiles (names shown throughout UI); `UPDATE` only by self or admin. No INSERT policy — rows are created only by the trigger.

Relationships: parent to nearly every other table (referenced by `workflow_definitions.created_by`, `requests.requester_id`/`deleted_by`, `workflow_stages.assigned_to`/`decided_by`, `notifications.recipient_id`, `audit_logs.actor_id`, `comments.author_id`/`deleted_by`, `attachments.uploaded_by`/`deleted_by`).

### `workflow_definitions`
**Purpose**: a versioned, JSON-encoded configuration of a request type's approval chain. Only one version per `request_type` may be active.
| Column | Type | Notes |
|---|---|---|
| `id` | uuid | PK |
| `request_type` | text | part of unique `(request_type, version)` |
| `version` | integer | `check >= 1` |
| `definition` | jsonb | validated `WorkflowDefinitionDocument` shape |
| `is_active` | boolean | default false |
| `created_by` | uuid | FK → `profiles(id)` |
| `row_version` | integer | default 1, `check > 0` |
| `created_at` | timestamptz | |

Unique partial index enforcing "at most one active version per request_type". RLS: SELECT visible if active or caller is admin; INSERT/UPDATE admin only.

### `requests`
**Purpose**: the central business entity — one submitted request, tracked to a terminal status.
| Column | Type | Notes |
|---|---|---|
| `id` | uuid | PK |
| `requester_id` | uuid | FK → `profiles(id)` |
| `workflow_definition_id` | uuid | FK → `workflow_definitions(id)` |
| `request_type` | text | |
| `title` | text | 1-200 chars |
| `description` | text | nullable, ≤5000 chars |
| `department` | text | nullable |
| `status` | request_status | default `pending` |
| `current_stage_id` | uuid | nullable, FK → `workflow_stages(id)` |
| `version` | integer | default 1, `check > 0` |
| `deleted_at`/`deleted_by` | timestamptz/uuid | soft-delete |
| `created_at`/`updated_at`/`completed_at` | timestamptz | |

8 indexes including a partial index on `(created_at desc) where deleted_at is null`. RLS: SELECT visible to requester, admin, or an assigned/role-eligible approver on one of its stages; INSERT only as self; UPDATE only requester-or-admin; no DELETE grant (soft-delete only).

### `workflow_stages`
**Purpose**: one runtime step instance in a request's approval chain.
| Column | Type | Notes |
|---|---|---|
| `id` | uuid | PK |
| `request_id` | uuid | FK → `requests(id)` ON DELETE CASCADE; part of unique `(request_id, stage_order)` |
| `stage_order` | integer | `check > 0` |
| `stage_name` | text | |
| `assigned_role` | user_role | nullable |
| `assigned_to` | uuid | nullable, FK → `profiles(id)` |
| `status` | stage_status | default `pending` |
| `decided_by` | uuid | nullable, FK → `profiles(id)` |
| `decided_at` | timestamptz | nullable |
| `decision_note` | text | nullable, ≤1000 chars |
| `version` | integer | default 1, `check > 0` |
| `created_at` | timestamptz | (no `updated_at`) |

RLS: SELECT visible to assignee, role-eligible callers, admin, or the parent request's requester; UPDATE only assignee/role-eligible/admin.

### `notifications`
**Purpose**: every notification generated for a user, with read/unread + email-dispatch + (since migration `0006`) archive tracking.
| Column | Type | Notes |
|---|---|---|
| `id` | uuid | PK |
| `recipient_id` | uuid | FK → `profiles(id)` |
| `request_id` | uuid | nullable, FK → `requests(id)` ON DELETE CASCADE |
| `notification_type` | notification_type | |
| `message` | text | |
| `is_read`/`read_at` | boolean/timestamptz | |
| `email_sent`/`email_sent_at` | boolean/timestamptz | |
| `created_at` | timestamptz | |
| `archived_at` | timestamptz | nullable, added in `0006` |

RLS: SELECT/UPDATE only by own recipient or admin — no INSERT grant (system-generated only, via service-role client). **Note**: this table's policies are named `notifications_select_own`/`notifications_update_own`, breaking from every other table's `<table>_select`/`<table>_update` naming convention — this caused a real migration-downgrade bug, already fixed this session (see Section 11).

### `audit_logs`
**Purpose**: immutable, append-only record of every state-changing action.
| Column | Type | Notes |
|---|---|---|
| `id` | uuid | PK |
| `actor_id` | uuid | nullable, FK → `profiles(id)` (null = system action) |
| `request_id` | uuid | nullable, FK → `requests(id)` |
| `action` | text | plain text; see `AuditAction` domain enum for the closed value set |
| `metadata` | jsonb | nullable |
| `created_at` | timestamptz | |

RLS: **SELECT only** — no INSERT/UPDATE/DELETE grant at all; written exclusively by the service-role client.

### `comments`
**Purpose**: threaded, immutable remarks on a request (added in `0004`).
| Column | Type | Notes |
|---|---|---|
| `id` | uuid | PK |
| `request_id` | uuid | FK → `requests(id)` ON DELETE CASCADE |
| `author_id` | uuid | FK → `profiles(id)` ON DELETE RESTRICT |
| `parent_comment_id` | uuid | nullable, self-FK ON DELETE CASCADE |
| `body` | text | 1-5000 chars |
| `deleted_at`/`deleted_by` | timestamptz/uuid | soft-delete |
| `created_at` | timestamptz | (no `updated_at` — immutable) |

RLS: SELECT to admin/requester/eligible approver; INSERT only as self, if requester or eligible approver; UPDATE (moderation) admin only.

### `attachments`
**Purpose**: file metadata (bytes live in Supabase Storage), with a version/replace chain (added in `0005`).
| Column | Type | Notes |
|---|---|---|
| `id` | uuid | PK |
| `request_id` | uuid | FK → `requests(id)` ON DELETE CASCADE |
| `uploaded_by` | uuid | FK → `profiles(id)` ON DELETE RESTRICT |
| `file_name`/`content_type` | text | |
| `size_bytes` | bigint | `check > 0` |
| `storage_path` | text | **unique** |
| `checksum_sha256` | text | |
| `version` | integer | default 1 |
| `replaces_attachment_id` | uuid | nullable, self-FK ON DELETE SET NULL |
| `scan_status` | text | default `skipped`, `check in (skipped, clean, infected, scan_error)` |
| `deleted_at`/`deleted_by` | timestamptz/uuid | soft-delete |
| `created_at` | timestamptz | |

RLS: SELECT admin/requester/eligible approver; INSERT self as requester/eligible approver; UPDATE (moderation) admin, or the uploader — but only while the parent request is still `pending`.

### The `on_auth_user_created` trigger (migration `0002`)
A `security definer` Postgres function/trigger firing `after insert on auth.users`: resolves the new user's role from `raw_user_meta_data->>'role'` (falling back to `employee` if absent/invalid), inserts a `profiles` row (`full_name` from metadata or email fallback), `on conflict (id) do nothing` for idempotency. Without this trigger, every login fails with "account not fully provisioned."

### Known migration gotcha (already fixed this session)
Migration `0003`'s `downgrade()` generic policy-drop loop assumed every table's SELECT policy is named `<table>_select`; `notifications`' is actually `notifications_select_own`, so the generic drop silently no-op'd, leaving a policy dependent on `current_profile_role()` behind and causing the subsequent `drop function` to fail with `DependentObjectsStillExist`. Fixed by adding explicit drop statements for the two irregularly-named policies before the generic loop runs.

---

## 6. Backend

### API Endpoints (17 routers, all mounted under `/api/v1` except `health`)

| Router | Endpoints (method + path) |
|---|---|
| `health.py` | `GET /health` |
| `auth.py` | `GET /auth/me` |
| `requests.py` | `POST /requests`, `GET /requests`, `GET /requests/{id}`, `PATCH /requests/{id}`, `DELETE /requests/{id}`, `GET /requests/{id}/workflow`, `GET /requests/{id}/workflow/current`, `GET /requests/{id}/workflow/history`, `GET /requests/{id}/approval-eligibility`, `GET /requests/{id}/audit-log` |
| `comments.py` | `GET /requests/{id}/comments`, `POST /requests/{id}/comments`, `DELETE /comments/{id}` |
| `dashboard.py` | `GET /dashboard-summary` |
| `attachments.py` | `GET /requests/{id}/attachments`, `POST /requests/{id}/attachments`, `PUT /attachments/{id}`, `GET /attachments/{id}/download`, `DELETE /attachments/{id}` |
| `approvals.py` | `GET /approvals/inbox`, `POST /approvals/{stage_id}/approve`, `POST /approvals/{stage_id}/reject`, `POST /approvals/bulk-approve`, `POST /approvals/bulk-reject` |
| `notifications.py` | `GET /notifications`, `GET /notifications/unread-count`, `POST /notifications/{id}/read`, `POST /notifications/read-all`, `POST /notifications/{id}/archive`, `POST /notifications/{id}/unarchive` |
| `activity.py` | `GET /activity/mine` |
| `workflow_definitions.py` | `GET /workflow-definitions`, `POST /workflow-definitions`, `PATCH /workflow-definitions/{id}`, `POST /workflow-definitions/{id}/activate` |
| `analytics.py` | `GET /analytics/dashboard` (csv), `/approvals`, `/workflow/{type}`, `/departments/{dept}` (csv), `/users/{id}`, `/workload` (csv), `/trend` (csv), `/summary/executive`, `/summary/operational`, `/summary/workflow/{type}`, `/summary/department/{dept}`, `/summary/user/{id}`, `/aging-requests` (admin only), and `GET /audit-logs` (admin only, org-wide) |
| `admin_users.py` | `GET /admin/users`, `GET /admin/users/{id}`, `PATCH /admin/users/{id}`, `GET /admin/users/{id}/activity` |
| `admin_roles.py` | `GET /admin/roles` (read-only permission matrix) |
| `admin_departments.py` | `GET /admin/departments`, `GET /admin/departments/{dept}/workload` |
| `admin_settings.py` | `GET /admin/settings` (read-only) |
| `admin_dashboard.py` | `GET /admin/dashboard` |

Every analytics endpoint self-enforces `rbac.require_role(APPROVER, ADMIN)` inline (the underlying engines perform no role check themselves). Out-of-scope resources are consistently reported as 404, never 403, to avoid confirming existence to an unauthorized caller.

**App assembly** (`app/api/main.py`): `create_app()` factory; middleware stack (outermost→innermost): `CORSMiddleware` → `RequestIDMiddleware` → `SecurityHeadersMiddleware` → `RequestLoggingMiddleware`. Exception handlers registered for every error root, plus a catch-all that never leaks a stack trace. Lifespan builds `ApplicationResources` once at startup; on shutdown, gracefully stops the scheduler only if this instance is the leader.

### Services (`app/services/*.py`)
- **`analytics_service.py`** — narrow, approver/admin-gated wrapper (Stack A); feeds only `DashboardService`.
- **`approval_service.py`** — stage decisions, escalation execution, pending-approvals inbox.
- **`attachment_service.py`** — upload/replace/remove/list, Storage + virus-scan integration point.
- **`comment_service.py`** — threaded comments + admin moderation.
- **`dashboard_service.py`** — pure composition layer (no repository access) assembling the personal dashboard summary.
- **`notification_service.py`** — the notification stack actually in use (one method per `NotificationType`).
- **`request_service.py`** — central request lifecycle orchestrator (create/read/list/search/update/withdraw).
- **`search_service.py`** — cross-entity fuzzy search (server-side prefilter + `difflib` scoring, not true full-text/trigram search).
- **`workflow_definition_service.py`** — definition lifecycle (create/edit-draft/activate); also defines the shared `TransactionContext` compensation-based orchestration primitive.

### Workflow Engine — see Section 8 (dedicated).

### Authentication & Permissions — see Section 9 (dedicated).

### Background Jobs (`app/scheduler/*.py`)
APScheduler `BackgroundScheduler`, `IntervalTrigger`, `max_instances=1`, `coalesce=True`, plus an additional application-level per-job lock (skipped-overlap tracked in stats, not queued).
- **`EscalationJob`** ("escalation_check") — hourly (`SCHEDULER_ESCALATION_INTERVAL_MINUTES`, default 60): finds overdue pending stages, escalates each via `ApprovalService.escalate_stage`.
- **`ReminderJob`** ("reminder_dispatch") — daily (`SCHEDULER_REMINDER_INTERVAL_HOURS`, default 24): sends a reminder to a stage's specific assignee once within 4 hours of its escalation threshold, with duplicate-suppression.
- **`HealthCheckJob`** ("scheduler_health_check") — fixed 5 minutes (hardcoded, not configurable): logs an in-memory snapshot of scheduler statistics; not exposed via any API endpoint.
- **`SCHEDULER_LEADER`** — a manual, operator-enforced single-instance convention (env var, default false); jobs are only constructed/started if true. Not real distributed leader election — misconfiguring two instances as leader would double-run jobs.

### Integrations
- **Supabase**: Auth, Postgres (via PostgREST), Storage (attachments).
- **SMTP**: generic `smtplib`-based email sending, conditional on `SMTP_HOST` being configured; failure never blocks the always-persisted in-app notification.
- **Virus scanning**: a real integration *point* exists (`AttachmentService`), but the only implementation present is `NullVirusScanner`, which always reports `SKIPPED` — no actual scanning engine is wired in.

---

## 7. Frontend

### Pages (Next.js App Router)
Top-level: `/` (redirects to `/dashboard`), `/login`, `/unauthorized`, plus global `not-found.tsx`/`error.tsx`.
`(app)` group (shared authenticated shell): `/dashboard`, `/requests`, `/requests/new`, `/requests/[id]`, `/approvals`, `/approvals/[stageId]`, `/analytics`, `/activity`, `/notifications`, `/workflows`, `/workflows/[requestType]/[version]`, `/admin`, `/admin/users`, `/admin/roles`, `/admin/departments`, `/admin/settings`.

### Layout
Root layout: `ThemeProvider` → `QueryProvider` → `AuthProvider` → `TooltipProvider` → children, plus a global toast `Toaster`. App-group layout wraps children in `AppShell` (`Sidebar` + `Header` + capped-width scrollable `main`), and mounts two session-wide singleton overlays: `CommandPalette` (⌘/Ctrl+K) and `KeyboardShortcutsDialog` (`?`).

### State management
TanStack Query only (no Redux/Zustand/Jotai). Query client default `staleTime: 60s`, `retry: 1`; individual hooks override per-query as needed. Auth session mirrors the Supabase browser client's own session via `onAuthStateChange`, exposed through a thin `AuthProvider` context. A custom "remember me" mechanism compensates for `@supabase/ssr`'s hardcoded 400-day cookie `maxAge` (no supported way to shorten it) using `localStorage`+`sessionStorage`.

### Routing
Next.js middleware (`src/middleware.ts` → `src/lib/supabase/middleware.ts`) checks only "is there a session" — redirects unauthenticated users to `/login`, redirects authenticated users away from `/login`. **No role-based protection at the middleware level.** `/admin/*` role-gating is client-side only (`(app)/admin/layout.tsx`, explicitly documented in its own comment as a usability convenience, not real enforcement — the real enforcement is server-side 403s).

### Forms
`react-hook-form` + `zod` (`@hookform/resolvers/zod`) uniformly across every form found (request create/edit, login, admin user-edit, workflow-designer stage editor, comment composer). The workflow-stage schema explicitly mirrors the backend's own Pydantic validation rules per its own code comment (no client-invented rules).

### Tables
Shared `DataTable` pattern (`@tanstack/react-table`): client-side sort on the loaded page, server-side pagination and filtering (passed as query params, not TanStack's built-in row models), `localStorage`-persisted column visibility. Used by Requests, Approvals, Admin Users, Admin Roles (permission matrix).

### Dashboards
`KpiCard`/`KpiRow` is the single shared metric-tile component, reused identically by Dashboard, Analytics, and Admin Dashboard. `BarChart`/`TrendChart` (Recharts) back status-breakdown/department-comparison/trend visualizations. `ChartSkeleton` avoids layout shift while loading.

### Shared components
- **`components/ui/`** — ~28 shadcn-derived primitives (form: input/textarea/select/checkbox/label; overlay: dialog/sheet/popover/dropdown-menu/context-menu/command/tooltip/alert-dialog; structure: card/tabs/accordion/resizable/scroll-area/table; feedback: badge/skeleton/sonner/progress).
- **`components/patterns/`** — composed patterns: `PageHeader`, `EmptyState`, `ErrorState`, `StatusBadge`, `Breadcrumbs`, `ConfirmDialog`, `DayGroupedList`, `DefinitionList`, `Dropzone`, `KeyboardShortcutsDialog`, `SavedViewsMenu`, `CommandPalette`, plus the `data-table/` and `charts/` sub-families.
- **`components/layout/`** — `AppShell`, `Header`, `Sidebar`, `SidebarBrand`, `NavLinks`/`nav-items.ts`, `MobileNavSheet`, `ThemeToggle`, `UserMenu`.

### Feature modules (`src/features/*`)
`activity`, `admin`, `analytics`, `approvals`, `auth`, `dashboard`, `notifications`, `profile`, `requests` (the largest), `workflow-designer` — each owns its own `components/`, `hooks/` (61 hook files total across all features), and where relevant `schemas/`/`query-keys.ts`. Every service call goes through a thin per-resource wrapper in `src/services/` before reaching a feature hook — the one exception is login, which calls Supabase directly since no session exists yet.

---

## 8. Workflow Engine

### Current implementation
`app/workflow/engine.py`'s `WorkflowEngine` is a **pure, I/O-free facade** — no component in this package ever queries a database; all inputs are already-fetched plain data, all outputs are plain results. It composes: `DefinitionResolver` (finds the active definition for a request type), `StageGenerator` (produces stage 1, or the next stage given the current one), `AssignmentResolver` (resolves who a stage is assigned to), `EscalationManager` (computes overdue-ness and the escalation fallback), `VersionManager` (version numbering + activation validation), plus a free-function `state_machine` module (fixed status-transition tables) and a `validators` module (structural + cross-referential definition validation).

Stages are generated **incrementally**, one at a time, never as a whole chain up front — `next_stage` is only computed once the current stage is decided.

### Supported workflow types
Any number of distinct `request_type` strings, each with its own independently versioned `workflow_definitions` chain. The demo dataset currently seeds 9: `leave_request`, `expense_reimbursement`, `purchase_order`, `access_request`, `hardware_request`, `software_request`, `travel_request`, `contract_request`, `recruitment_request` — each a 2-stage chain (Manager Review → Final Sign-off) in the seeded data, though the engine itself supports any number of stages per definition.

### Approval flow
Three assignment strategies per stage, chosen in the definition:
- **`specific_user`** — a named user id, validated to exist at authoring time, never re-validated at runtime (definitions are immutable once active).
- **`department_queue`** — no specific user; any approver with the matching role is eligible, first to act wins under optimistic locking (a losing concurrent attempt raises `ConcurrencyError`).
- **`requester_manager`** — resolved at runtime against the requester's own `department` (there is **no manager-hierarchy column** in `profiles` — this is an explicitly documented simplification, "the department's designated approver" standing in for "the requester's manager"), choosing the alphabetically-first-by-name candidate deterministically. Falls back to `admin` if no eligible department approver exists.

A decision (`approve_stage`/`reject_stage`) is authorized, applied under optimistic locking, audited, and notified; approval either generates the next stage or completes the request; rejection terminates it.

### Status management
Fixed transition tables (`state_machine.py`): requests `PENDING → {IN_REVIEW, REJECTED, COMPLETED}`, `IN_REVIEW → {IN_REVIEW, COMPLETED, REJECTED}`; `APPROVED` reserved/unreachable; `COMPLETED`/`REJECTED` terminal. Stages: `PENDING → {PENDING (escalation reassignment), APPROVED, REJECTED, SKIPPED}`; the other three terminal.

Escalation: threshold = `stage.created_at + escalation_hours`, recomputed on demand (never persisted as a column, so it survives a process restart correctly). Escalating a stage reassigns it (no new stage row) to the `admin` fallback, using the same optimistic-locking predicate a human decision uses — a concurrent human decision always wins a race against a stale escalation attempt.

### Limitations
- No conditional/branching stages — `StageStatus.SKIPPED` exists as an enum value but is never produced by any current strategy (a documented forward-looking hook).
- `requester_manager` is a department-based approximation, not a true reporting-line lookup (no data model supports a real manager hierarchy).
- A definition, once activated, cannot be edited — only superseded by a new version.
- No parallel/multi-approver-per-stage support — one stage has exactly one eventual decider.
- `TransactionContext` (used across services for multi-step persistence) is **compensation-based, not true database-transaction ACID** — a partial failure triggers a best-effort rollback of already-completed steps, not a real `ROLLBACK`.

---

## 9. Authentication & Authorization

### Login
Frontend calls Supabase directly (`supabase.auth.signInWithPassword`), bypassing the FastAPI backend entirely — login precedes having a session, so there's nothing for the backend's stateless-bearer-token model to check yet. No custom password policy is enforced client- or server-side beyond Supabase's own; `app/auth/password.py`'s PBKDF2 utilities exist but are unused (Supabase owns real credential storage).

### Roles
Exactly three: `employee`, `approver`, `admin` — additive (`approver ⊇ employee`, `admin ⊇ approver`), defined declaratively in `app/auth/permissions.py`'s `ROLE_PERMISSIONS` and enforced via pure predicate functions in `app/auth/rbac.py` (e.g. `can_view_request`, `can_edit_request`, `can_decide_stage`, `can_moderate_comment`, `can_manage_user_roles`). Notably, `can_edit_request` **ignores role entirely** — not even an admin may edit another user's request fields; only the requester (while pending) can.

### Permissions
Enforced at the service layer via `app/auth/authorization.py`'s `authorize_*` functions, which wrap the `rbac` predicates and raise typed exceptions (`OwnershipRequiredError`, `PermissionDeniedError`, `RoleNotPermittedError`) on failure. Out-of-scope requests are deliberately reported as 404 (via a catch-and-reraise pattern), never 403, so an unauthorized caller can't confirm a resource's existence. Postgres RLS mirrors these rules as defense-in-depth (the app's actual service-role client bypasses RLS at runtime).

### Session handling
**Stateless — no server-side session exists.** Every API request carries a bearer token; `SupabaseTokenVerifier.resolve_claims` makes a real network call to Supabase (`client.auth.get_user(token)`) on **every single request**, then resolves the role fresh from `profiles` (never trusting a role embedded in the JWT). The resulting `AuthenticatedIdentity` lives only for that one request. On the frontend, the Supabase browser client manages its own token refresh; the Next.js middleware refreshes/validates the session cookie on every navigation; the API client additionally attempts one `refreshSession()` + retry before signing a user out on a persistent 401.

### Security
- CORS restricted to `CORS_ALLOWED_ORIGINS` (default `http://localhost:3000`).
- `SecurityHeadersMiddleware` + `RequestIDMiddleware` on every request.
- No stack traces ever reach a client response — a catch-all exception handler logs full detail server-side, correlated only via `request_id`.
- Rate limiting is **configured via env vars** (`RATE_LIMIT_READ_PER_MINUTE` etc.) but this pass did not confirm an actual enforcing middleware exists wired to those values — flagged as unconfirmed, not verified either way in the research performed for this document.
- A transient database error during token verification is deliberately **not** mistranslated into a 401 (a real bug fixed this session) — it propagates to a retryable 500 instead, so a one-off DB hiccup can no longer force-log-out an otherwise valid session.

---

## 10. Current Features

| Feature | Status |
|---|---|
| Request create/view/list/search/edit/withdraw | **Complete** |
| Multi-stage configurable workflow engine (3 assignment strategies) | **Complete** |
| Automatic escalation on overdue stages | **Complete** |
| Approval inbox, single + bulk decisions | **Complete** |
| Threaded comments + admin moderation | **Complete** |
| Attachments (upload/replace/remove/download, versioned) | **Complete** (virus scanning is a wired *point*, but the only implementation present always skips) |
| In-app notifications (list/unread/read/archive) | **Complete** |
| Email notification dispatch | **Complete**, conditional on SMTP config, best-effort (never blocks in-app persistence) |
| Personal dashboard (KPIs, recent requests, activity, charts) | **Complete** |
| Analytics — executive/operational/explorer views, CSV export | **Complete**, but split across two unreconciled backend stacks (Section 1/16) |
| Admin: user directory, role/department edit | **Complete** |
| Admin: read-only permission matrix | **Complete** |
| Admin: department workload view | **Complete** (no Department entity — free-text grouping only) |
| Admin: platform settings viewer | **Complete**, read-only (no PATCH endpoint) |
| Visual workflow designer (React Flow), versioning, diff, autosave, undo/redo | **Complete** |
| Audit trail (per-request + org-wide admin feed) | **Complete** |
| RBAC (employee/approver/admin) | **Complete**, server-enforced + RLS defense-in-depth |
| Background jobs: escalation, reminder, health-check | **Complete** |
| Nightly analytics aggregation job | **Planned/configured only** — env var exists, no job class implemented |
| Cross-request-type "all workflow definitions" count | **Partial** — hardcoded to one request type only |
| Password reset / user invite flow | **Missing** — no such endpoints exist |
| Health endpoint exposing scheduler stats | **Missing** — data exists in memory, no route serves it |
| Conditional/branching workflow stages | **Missing** — enum value reserved, no implementation |
| True manager-hierarchy-based routing | **Missing** — department-based approximation only |
| Frontend CI (build/lint in GitHub Actions) | **Missing** |
| Containerized deployment | **Missing** |

---

## 11. Known Issues

### Bugs (fixed this session, documented for history)
- **RLS migration downgrade bug** (`0003_row_level_security.py`) — wrong policy name assumed for `notifications`, causing `alembic downgrade` to fail with `DependentObjectsStillExist`. Fixed.
- **Auth false-logout bug** — a transient database error during the post-token-verification profile lookup was mislabeled as an invalid-token 401, forcing valid sessions to sign out on a one-off DB hiccup. Fixed (now propagates as a retryable 500).
- **Frontend 401 handling** — the API client previously signed a user out unconditionally on the first 401 with no retry. Fixed to attempt one silent `refreshSession()` + retry first.
- **Search-bar crash** — `CommandDialog` rendered cmdk sub-components without the `Command` root providing their store context. Fixed.
- **Analytics/Dashboard 400 at scale** — `AnalyticsRepository.approval_throughput` built a `request_id IN (...)` filter with one UUID per matching request; at ~650 seeded requests this exceeded the Supabase gateway's URL-length limit, breaking both Dashboard and Analytics. Fixed via an embedded-join query instead of an explicit id list.

### Currently open, confirmed via this pass
- **`README.md`'s documented run command is stale/wrong**: `uvicorn app.api.main:app --reload` — but `app/api/main.py` defines **only** a `create_app()` factory function, no module-level `app` object. The correct invocation is `uvicorn app.api.main:create_app --factory --reload`. See Section 14 for the corrected commands.
- **`README.md`'s test-coverage command references a nonexistent path**: `pytest --cov=src --cov-report=term-missing` — there is no `src/` directory; `pyproject.toml`'s own coverage config uses `source = ["app"]`.
- **`README.md`'s Architecture Overview and Repository Structure sections still describe the removed Streamlit UI** (`src/ui/` Streamlit pages, `src/analytics/` Plotly dashboards) — internally inconsistent with the same README's own (correct) Technology Stack table just above it.
- **`README.md`'s "Documentation Index" links to files that don't exist** (`docs/SRS.md`, `docs/ADD.md`, `docs/DSD.md`, `docs/API-ADD.md`, `docs/WEDD.md`, `docs/TSD.md`, `docs/DG.md`) — the actual files are `docs/requirements.md`, `architecture.md`, `database_schema.md`, `api_design.md`, `workflow_engine.md`, `testing_strategy.md`, `deployment.md`.
- **`pyproject.toml` lists `httpx2>=2.0`** in `[project.optional-dependencies].dev`, alongside `httpx>=0.27` — `httpx2` does not appear to be a legitimate, verifiable package; if it isn't real, `pip install -e ".[dev]"` (used in CI) would fail outright. Needs verification/correction.
- **`pytest.ini` still filters a Streamlit-specific deprecation warning** (`ignore::DeprecationWarning:streamlit.*`) — inert now that streamlit isn't installed via the project's own dependency files, but should be removed for cleanliness.
- **Stale in-code comments** describing Streamlit/Plotly as current or future collaborators (in `app/bootstrap.py`, `app/services/dashboard_service.py`, `app/services/attachment_service.py`, `app/services/analytics_service.py`, and several module docstrings) — mostly harmless but inaccurate; one (`dashboard_service.py`) describes Streamlit as a *future* consumer, which is backwards.
- **`docs/*.md` design documents** (architecture, API design, DB schema, workflow engine, testing strategy, deployment, design philosophy) still describe Streamlit as the live UI framework throughout, not flagged as historical.

### Performance bottlenecks
- Every authenticated request makes a real network round trip to Supabase to verify the token (by design, for statelessness) — no caching layer exists to reduce this; under load this is the most significant fixed per-request latency cost in the system.
- `AnalyticsEngine`'s fallback aggregation strategy (when no native repository aggregate exists) fetches the **complete** matching population client-side before aggregating — exact but potentially expensive at very large scale; there is no pagination/sampling cap on these specific code paths (a deliberate accuracy-over-performance tradeoff per its own documentation, not an oversight).
- `GlobalSearchService` uses a server-side ILIKE prefilter plus in-process `difflib` fuzzy scoring — not a true full-text/trigram search; could degrade at large table sizes since no `pg_trgm` index exists.

### Technical debt
- Two unreconciled analytics stacks (`app/services/analytics_service.py` vs `app/analytics/analytics_engine.py`) — deliberate at the time each was built, but now a genuine duplication with no plan visible in the code to unify them.
- ~~Two unreconciled notification stacks~~ — resolved: `app/notifications/*`'s unused orchestration layer (`NotificationManager`/`NotificationFactory`/`InAppNotifier`/`templates`) was removed; `app/services/notification_service.py` is the sole notification implementation. `app/notifications/*` now contains only the low-level SMTP toolkit (`SmtpEmailProvider`/`EmailProvider`) it and two other real call sites share.
- `app/auth/decorators.py` and `app/auth/password.py` are complete, tested-looking infrastructure with **no call sites** anywhere in the routers/services.
- Router-level RBAC checks are inconsistent in pattern (some inline `rbac.require_role` calls, admin routers vary in count) — not confirmed to be duplicated/copy-pasted logic, but not consolidated either.

### TODOs / temporary implementations
- No literal `TODO`/`FIXME`/`HACK`/`XXX` comments exist anywhere in `app/` or `frontend/src/` (confirmed by direct grep) — the one match in `app/services/attachment_service.py` is a docstring *asserting* virus scanning is not a stub, not an open TODO.
- The virus-scanning integration point's only implementation (`NullVirusScanner`) is itself a permanent, documented no-op stand-in — a real scanner would need to be substituted at the composition root.

### Dead code
- `app/auth/decorators.py`'s three decorators — defined, unused.
- `app/auth/password.py`'s hash/verify functions — defined, unused.
- `frontend/public/*.svg` (file.svg, globe.svg, next.svg, vercel.svg, window.svg) — these are the default Next.js starter template assets; not confirmed to be referenced anywhere in the actual UI (worth a quick grep before deleting, not independently verified in this pass).

---

## 12. Migration Status

### What was migrated from Streamlit
The application previously had a Streamlit-based Presentation Layer (`app.py`, `app/pages/*.py` — dashboard, requests, approvals, analytics, workflows, admin, login, profile, session, navigation, components, global_search, notifications, plus a `theme.css` and `.streamlit/` config). **All of it has been deleted** this session:
- `app.py`, all 11+ files under `app/pages/` (including untracked leftovers discovered via mypy after the initial git-tracked deletion: `global_search.py`, `notifications.py`, `theme.py`, `assets/theme.css`).
- `.streamlit/config.toml`, `.streamlit/secrets.toml.example`.
- `app/auth/session_manager.py` (Streamlit-only `InMemorySessionStore`/`Session`/`SessionManager` — dead once the stateless JWT model replaced it), and its exports removed from `app/auth/__init__.py`.
- `StreamlitSettings` dataclass and its field on `AppSettings` (`app/config/settings.py`), and its associated env-var constants (`app/config/constants.py`).
- `streamlit>=1.32` and `plotly>=5.19` removed from both `pyproject.toml` and `requirements.txt`; `requirements.txt` additionally gained `fastapi`/`uvicorn[standard]`/`python-multipart` to match `pyproject.toml` (previously missing/inconsistent).
- The `STREAMLIT_SERVER_ADDRESS`/`STREAMLIT_SERVER_PORT` block removed from `.env`/`.env.example`.

The React/Next.js frontend under `frontend/` is the complete, functional replacement — every page the Streamlit app had now has a Next.js equivalent (confirmed in Section 7).

### What still depends on Streamlit
**Nothing functionally.** No code in `app/` or `frontend/` imports or requires streamlit/plotly (confirmed by grep across the whole repo, excluding `.venv` and lock files). The dependency is fully removed from both `requirements.txt` and `pyproject.toml`.

### What can safely be removed
- The `pytest.ini` line filtering a streamlit-specific `DeprecationWarning` (inert).
- The `.gitignore` block referencing `.streamlit/secrets.toml` (harmless no-op, but no longer needed).
- A locally-installed `streamlit`/`plotly` package may still physically exist in a developer's `.venv` if it predates this session's cleanup — irrelevant to the repository itself (`.venv/` is gitignored), but worth a `pip uninstall` locally for hygiene. A fresh `pip install -r requirements.txt` would never reintroduce it.

### Legacy files/documentation no longer accurate
- **`README.md`** — Architecture Overview, Repository Structure, and Documentation Index sections still describe the old Streamlit-based `src/` layout and reference nonexistent doc filenames (Section 11 has full detail). This is the single most visible remaining inconsistency, since it's the first file a new engineer reads.
- **`docs/*.md`** — the original design documents (architecture, API design, DB schema, workflow engine, testing strategy, deployment, design philosophy) describe Streamlit as the current/live UI throughout; they read as historical specification documents but are not labeled as such. Whether to update or explicitly archive/label them as historical is a judgment call not resolved in this pass.
- Several backend module docstrings (`app/bootstrap.py`, `app/services/dashboard_service.py`, `app/services/attachment_service.py`, `app/services/analytics_service.py`) retain Streamlit-era framing in their prose — mostly harmless, one (`dashboard_service.py`) is actively backwards (describes Streamlit as a future consumer rather than a removed past one).

---

## 13. Configuration

### Environment variables — backend (`.env.example`)
| Variable | Purpose |
|---|---|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_ANON_KEY` | Public/anon key (safe for anon-scoped calls) |
| `SUPABASE_SERVICE_ROLE_KEY` | Server-only key; bypasses RLS — never expose to a browser |
| `DATABASE_URL` | Direct Postgres connection string, used only by Alembic |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USERNAME` / `SMTP_PASSWORD` / `SMTP_FROM_ADDRESS` | Email dispatch config; notification email sending is disabled entirely if `SMTP_HOST` is unset |
| `SCHEDULER_LEADER` | Must be `true` on exactly one running instance — enables background jobs on that process |
| `SCHEDULER_ESCALATION_INTERVAL_MINUTES` (default 60) / `SCHEDULER_REMINDER_INTERVAL_HOURS` (default 24) / `SCHEDULER_ANALYTICS_INTERVAL_HOURS` (default 24, unused — see Section 1) | Job intervals |
| `LOG_LEVEL` | Structured logging verbosity |
| `RATE_LIMIT_READ_PER_MINUTE` / `_WRITE_PER_MINUTE` / `_UPLOAD_PER_MINUTE` / `_LOGIN_PER_5_MINUTES` / `_NOTIFICATION_POLL_PER_MINUTE` | Rate-limit configuration values (enforcing middleware not independently confirmed in this pass) |
| `WORKFLOW_DEFAULT_ESCALATION_HOURS` | Default escalation threshold for new workflow stages |

### Environment variables — frontend (`frontend/.env.local.example`)
| Variable | Purpose |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | Same Supabase project URL, browser-exposed |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Anon key only — safe for the browser |
| `NEXT_PUBLIC_API_BASE_URL` | FastAPI backend base URL (defaults to `http://localhost:8000/api/v1`) |

### Config files
`pyproject.toml` (package metadata + deps + black/ruff/mypy/coverage config), `requirements.txt` (pinned production deps), `alembic.ini` (migration config, connection string resolved from env at runtime), `pytest.ini` (test paths/markers/coverage flags), `frontend/package.json`, `frontend/tsconfig.json`, `frontend/next.config.ts` (currently empty — no custom config), `frontend/eslint.config.mjs`, `frontend/components.json` (shadcn config), `frontend/postcss.config.mjs`.

### Required services
- A Supabase project (Postgres + Auth + Storage) — either the hosted cloud product or a self-hosted equivalent exposing the same URL/key/connection-string surface.
- An SMTP server, only if email notifications are desired (optional — the app runs fully without one, email dispatch simply no-ops).

### Startup commands
See Section 14 for the exact, verified commands.

---

## 14. Running the Project

### Install dependencies
```bash
# Backend (from repo root)
pip install -e ".[dev]"
# or, for a production-only install:
pip install -r requirements.txt

# Frontend
cd frontend
npm install
```

### Run backend
```bash
# Correct invocation — README.md's documented `uvicorn app.api.main:app --reload`
# is stale; app/api/main.py exposes only a factory function, not a module-level app object.
uvicorn app.api.main:create_app --factory --reload
```

### Run frontend
```bash
cd frontend
npm run dev      # dev server
npm run build    # production build
npm run start    # serve the production build
npm run lint      # ESLint
```

### Initialize database
```bash
# Apply all migrations
alembic upgrade head

# Or, the convenience wrapper (migrations + optional seed in one step):
python scripts/initialize_db.py
python scripts/initialize_db.py --seed
python scripts/initialize_db.py --seed --email dev@example.com --password "S0meP@ss"
```

### Reset database (destructive — downgrades to base, then upgrades to head again)
```bash
python scripts/reset_database.py                # interactive confirmation
python scripts/reset_database.py --yes          # skip prompt (e.g. CI)
python scripts/reset_database.py --yes --seed --email dev@example.com
```
Refuses to run against any environment where `Environment.requires_production_grade_hardening` is true (Staging/Production).

### Seed data
```bash
# Minimal: one admin user + default workflow definition(s)
python scripts/seed_demo_data.py
python scripts/seed_demo_data.py --email dev@example.com --password "S0meP@ss" --full-name "Dev Admin"

# Full realistic enterprise dataset (7 departments, ~65-70 users, ~650 requests)
python scripts/seed_enterprise_demo.py
python scripts/seed_enterprise_demo.py --requests 700 --users 80
python scripts/seed_enterprise_demo.py --admin-email dev@example.com --admin-password "S0meP@ss"

# Backfill activity for two specific already-existing named test accounts
python scripts/seed_profile_demo_data.py
```

### Run tests
```bash
pytest                     # full suite — integration tests auto-skip without a dedicated test Supabase project
pytest tests/unit          # unit tests only (in-memory fakes, no network)
pytest --cov=app --cov-report=term-missing   # with coverage (note: README.md's --cov=src is wrong — no src/ exists)

# Integration tests additionally require, to actually run rather than skip:
#   TEST_DATABASE_URL, TEST_SUPABASE_URL, TEST_SUPABASE_SERVICE_ROLE_KEY
# (see tests/integration/README.md — never point this at a production project)
```
Last verified run at time of writing: **242 passed, 55 skipped** (skips are entirely the integration suite, absent test-project credentials).

Lint/typecheck:
```bash
ruff check .
mypy app
```

---

## 15. Code Quality

### Duplicate code
- **Two analytics stacks** (`app/services/analytics_service.py` vs `app/analytics/analytics_engine.py`) — deliberate historically, unreconciled now.
- Frontend toolbar/filter-bar components (6 files, ~357 lines total) show partial but inconsistent reuse of the shared `DataTableToolbar` — `approval-inbox-toolbar.tsx` builds on it; `user-directory-toolbar.tsx` hand-rolls an equivalent search/tab-filter pattern instead. Not confirmed to be a large duplication, but a plausible consolidation candidate.

### Unused files/dependencies
- `app/auth/decorators.py` — three decorators, no call sites.
- `app/auth/password.py`'s hashing functions — no call sites (Supabase owns real credential handling).
- `pyproject.toml`'s `httpx2>=2.0` dev dependency — likely erroneous/unverifiable package name, needs a decision.
- `frontend/public/*.svg` — default Next.js starter assets, not confirmed to be referenced by the actual UI.

### Large files (candidates for splitting)
Backend, over 500 lines: `app/services/request_service.py` (960), `app/analytics/analytics_engine.py` (734), `app/services/attachment_service.py` (692), `app/services/approval_service.py` (676), `app/services/workflow_definition_service.py` (624), `app/database/repositories/base_repository.py` (578), `app/database/repositories/workflow_repository.py` (558, combines two repository classes), `app/api/routers/analytics.py` (551), `app/services/search_service.py` (549), `app/services/notification_service.py` (516). Each has a coherent single-responsibility docstring justifying its size rather than looking like accidental sprawl, but `analytics_engine.py`/`analytics.py` (router) are the most plausible candidates for splitting by metric category.

Frontend: only one file exceeds 500 lines — `frontend/src/features/auth/components/workflow-network.tsx` (513 lines, a hand-rolled Canvas 2D particle/graph animation engine for the login page; long by nature of manually managing animation state in one `requestAnimationFrame` closure, not disorganized).

### Suggested refactors
1. Reconcile or formally deprecate one of the two analytics stacks.
2. Remove or genuinely use `app/auth/decorators.py` and `app/auth/password.py`.
3. Split `app/analytics/analytics_engine.py` and `app/api/routers/analytics.py` by metric category (dashboard/workflow/department/user/trend) if they continue to grow.
4. Consolidate the frontend's toolbar/filter-bar pattern so every feature toolbar builds on `DataTableToolbar` rather than some hand-rolling an equivalent.
5. Fix `README.md`'s stale run command, coverage-path command, Architecture/Repository-Structure sections, and broken Documentation Index links (Section 11) — the highest-visibility, lowest-effort fix available.
6. Resolve the `httpx2` dependency anomaly in `pyproject.toml`.
7. Add a frontend job (install/lint/build, ideally `tsc --noEmit` too) to `.github/workflows/ci.yml` — currently completely unverified in CI.

---

## 16. Future Roadmap

Recommended next priorities, in logical order (dependencies first):

1. **Fix the CI gap** — add a frontend lint/typecheck/build job to `.github/workflows/ci.yml`. Cheapest, highest-leverage fix; currently a broken frontend build could merge to `main` silently.
2. **Correct `README.md`** — the stale run command, coverage path, Architecture/Repository-Structure sections, and broken doc-index links (Section 11) are the first thing any new engineer or AI assistant will read and currently actively mislead.
3. **Resolve the two analytics stacks** — either formally retire `app/services/analytics_service.py` in favor of `AnalyticsEngine` everywhere (including `DashboardService`), or document clearly why both must remain. Duplication left unresolved compounds every time either stack is extended.
4. **Implement or remove the "Nightly Analytics Aggregation" job** — currently a configured-but-nonexistent feature; either build the job class or remove the unused settings/env var to stop implying a capability that doesn't exist.
5. **Decide on a real virus-scanning integration** — `NullVirusScanner` is a permanent no-op; if attachment safety matters for the target deployment, this is a real security gap, not just tech debt.
6. **Add a real health/readiness endpoint** exposing `HealthCheckJob`'s already-collected scheduler statistics — trivial to wire, meaningful for any real deployment/monitoring setup.
7. **Harden the `SCHEDULER_LEADER` story** — either implement real leader election (e.g. a Postgres advisory lock) or, at minimum, add a startup-time guard that detects and refuses a second leader against the same database, since misconfiguration currently fails silently into duplicate job execution.
8. **Containerize both services** and produce a documented, working deployment pipeline (`docs/deployment.md` exists as a design document but a working, verified pipeline was not confirmed to exist in this pass).
9. **Decide the fate of `docs/*.md`** — either update the original design documents to reflect the current Next.js/FastAPI architecture, or explicitly label them as historical/superseded so they stop presenting Streamlit as the live UI.
10. **Address the smaller, low-effort cleanups** from Section 11/15 (remove the stale pytest streamlit filter, resolve `httpx2`, remove or wire `app/auth/decorators.py`/`password.py`, verify/remove unused frontend starter SVGs) as routine hygiene once the above are underway.
11. **Only after the above**, consider genuinely new features: real manager-hierarchy-based routing (would require a schema change — a `manager_id` column or similar), conditional/branching workflow stages, parallel multi-approver stages, and a password-reset/invite-user admin flow.

---

## 17. AI Handoff

**What this is**: Enterprise Automation Hub — a FastAPI (Python 3.11+) + Supabase (Postgres/Auth/Storage) backend, paired with a Next.js 15 / React 19 / TypeScript frontend, implementing configurable multi-stage approval workflows for organizational requests (leave, expense, purchase, access, hardware, software, travel, contract, recruitment). It used to also have a Streamlit UI; that has been **fully removed** — Next.js is now the only frontend.

**Architecture, in one sentence**: strictly layered modular monolith — FastAPI routers → Application Services (`app/services/*.py`) → a pure, I/O-free Workflow Engine (`app/workflow/*.py`) + Domain Models (`app/models/*.py`) → Repositories (`app/database/repositories/*.py`, one per table) → Supabase, with everything wired together once at startup by `app/bootstrap.py`'s `build_application_resources()`.

**Auth model**: stateless. Every request carries a Supabase JWT; the backend re-verifies it against Supabase on every single request (no session cache) and always resolves the caller's role fresh from the `profiles` table (never trusts the JWT's own claims). Three roles: `employee` < `approver` < `admin`, enforced by pure predicate functions in `app/auth/rbac.py`.

**Database**: 8 tables (`profiles`, `workflow_definitions`, `requests`, `workflow_stages`, `notifications`, `audit_logs`, `comments`, `attachments`), full schema in Section 5 of this document — read that section before writing any migration or repository code, it is the ground truth, sourced directly from the 6 Alembic migration files.

**The single most important non-obvious fact for anyone extending this codebase**: **there are two parallel, unreconciled implementations for analytics** — `app/services/analytics_service.py` (narrow, feeds only the personal dashboard) vs. `app/analytics/analytics_engine.py` (rich, backs the actual `/analytics` page — this is the one to extend). Picking the wrong stack to modify will produce code that runs, tests green in isolation, but has no effect on the running application. (Notifications used to have this same trap — a second, fully-built-but-uncalled `app/notifications` orchestration stack — but it was removed; `app/services/notification_service.py` is now the sole notification implementation, and `app/notifications/*` is only the low-level SMTP toolkit it, `invitation_email.py`, and `app/jobs/handlers.py` share.)

**Other load-bearing facts**:
- The workflow engine never touches a database — it's pure functions over already-fetched data, composed by `app/workflow/engine.py`. Three assignment strategies exist (`specific_user`, `department_queue`, `requester_manager`); the last is a department-based approximation since there's no real manager-hierarchy column.
- Escalation thresholds are computed on demand (`stage.created_at + escalation_hours`), never persisted — this is intentional and survives process restarts correctly.
- `TransactionContext` (used across services) is compensation-based, not a real database transaction — don't assume ACID guarantees across multi-step service operations.
- The frontend has **no global client-state library** — TanStack Query is the only server-state layer; don't introduce Redux/Zustand without a strong reason.
- `/admin/*` role gating is client-side-only for UX; the real enforcement is server-side FastAPI 403s — never rely on the frontend guard for security.
- CI (`.github/workflows/ci.yml`) only lints/typechecks/tests the **backend** — the frontend build/lint is never verified in CI. Don't assume a green CI run means the frontend compiles.
- `README.md` has several stale/incorrect sections (wrong run command, wrong coverage path, Streamlit-era architecture description, broken documentation links) — don't trust it blindly; this `PROJECT_SUMMARY.md` document and direct source inspection are more reliable.
- Test suite: 242 passing unit/acceptance/security/performance tests using in-memory fakes (no network); the integration suite (5 files) requires a dedicated test Supabase project's credentials and silently skips without them — a green `pytest` run does not by itself prove the real database schema/RLS policies work correctly end-to-end.

**Where to start reading actual code**, in order of leverage: `app/bootstrap.py` (see everything wired together) → `app/workflow/engine.py` (the core business logic) → `app/services/request_service.py` and `approval_service.py` (the two central orchestrators) → `app/api/main.py` (how it all becomes an HTTP API) → `frontend/src/app/(app)/layout.tsx` and any one `features/*` folder (how the frontend consumes it).
