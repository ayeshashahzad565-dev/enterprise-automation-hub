# Enterprise Automation Hub (EAH)
## Architecture Design Document

**Version:** 1.0
**Status:** Baseline Architecture
**Author:** Principal Software Architect
**Stack:** Python 3.11, Streamlit, Supabase (PostgreSQL, Auth, Storage), Pydantic v2, APScheduler, Plotly, pytest

---

## 1. Executive Overview

Enterprise Automation Hub (EAH) is a modular monolithic application designed to manage internal business requests, approvals, and workflow automation for a small-to-mid-sized organization. The system is built as a single deployable Python application that uses Streamlit for its user interface and Supabase as its managed backend (PostgreSQL database, authentication provider, and object storage).

The architectural philosophy behind EAH rests on five principles:

**Maintainability.** The codebase is organized into clearly bounded layers, each with a single, well-defined responsibility. Business rules, data access, and presentation logic never overlap in the same module. A developer reading `src/services/` should never need to understand Streamlit widgets, and a developer reading `src/ui/` should never need to understand SQL.

**Separation of Concerns.** EAH separates *what the UI shows* from *what the application does* from *how data is persisted*. This separation is enforced through a layered architecture (Presentation → Application → Domain → Repository → Database) rather than through network boundaries. The layering is a discipline of the codebase, not a distributed system.

**Simplicity.** EAH deliberately avoids infrastructure that a solo developer or small team cannot operate sustainably. There is no message broker, no container orchestration platform, no distributed cache, and no event bus. Every capability in the system is implemented using the seven technologies listed in the stack. Simplicity is treated as a design goal in its own right, not as a temporary compromise.

**Testability.** Because business logic lives in plain Python classes and functions (the Application and Domain layers) rather than inside Streamlit callbacks, it can be exercised directly by pytest without spinning up a UI or a live database. Repositories are the only components that touch Supabase, and they are narrow enough to be mocked or swapped for test doubles.

**Production Readiness within a Monolith.** "Production-ready" in this context does not mean "distributed." It means: typed data contracts (Pydantic v2), fail-fast validation, immutable audit trails, role-based access control enforced both in application code and at the database level (Row-Level Security), structured error handling, and a scheduler for background automation — all running inside one well-organized process.

**Scalability within a Monolith.** EAH scales by scaling *Supabase* (connection pooling, read replicas, vertical scaling of the Postgres instance) and by scaling the *Streamlit deployment* horizontally behind a load balancer where sessions are stateless with respect to business data. The application logic itself scales because it is decoupled from the UI layer and can, in the future, be reused by a different front end without being rewritten.

EAH is intentionally scoped as a single Python package. There is no plan, implicit or explicit, to decompose it into services. Every design decision in this document should be read with that constraint in mind.

---

## 2. High-Level Architecture

The diagram below shows the full request path, including the background scheduler, which runs in-process alongside the Streamlit application.

```
                                   ┌────────────────────────────┐
                                   │           User             │
                                   │  (Employee / Approver /    │
                                   │   Administrator)           │
                                   └──────────────┬─────────────┘
                                                  │ HTTPS
                                                  ▼
                         ┌───────────────────────────────────────────┐
                         │              Streamlit UI                 │
                         │        (src/ui)                           │
                         │  - Pages: Requests, Approvals, Admin,     │
                         │    Analytics, Login                       │
                         │  - Session state management               │
                         │  - Form rendering & user input capture    │
                         └───────────────────┬───────────────────────┘
                                             │ calls typed functions
                                             ▼
                         ┌───────────────────────────────────────────┐
                         │           Application Services            │
                         │        (src/services)                     │
                         │  - RequestService                         │
                         │  - ApprovalService                        │
                         │  - CommentService                         │
                         │  - AttachmentService                      │
                         │  - AuditService                           │
                         │  - NotificationService                    │
                         │  - AnalyticsService                       │
                         │  - AuthService                            │
                         └──────┬───────────────────────┬────────────┘
                                │                       │
                                ▼                       ▼
                 ┌─────────────────────-──┐   ┌───────────────────────────┐
                 │      Domain Layer      │   │      Workflow Engine      │
                 │     (src/models)       │   │      (src/workflows)      │
                 │  - Pydantic v2 models  │   │  - Stage transitions      │
                 │  - Enums & value types │   │  - Assignment rules       │
                 │  - Business invariants │   │  - Configuration-driven   │
                 └───────────┬────────────┘   │    routing                │
                             │                └──────────────┬────────────┘
                             ▼                               │
                 ┌───────────────────────────────────────────┘
                 ▼
     ┌───────────────────────────────────────────┐
     │              Repository Layer             │
     │           (src/repositories)              │
     │  - RequestRepository                      │
     │  - ApprovalRepository                     │
     │  - CommentRepository                      │
     │  - AttachmentRepository                   │
     │  - AuditLogRepository                     │
     │  - UserRepository                         │
     └───────────────────┬───────────────────────┘
                         │ Supabase client (PostgREST / storage-py / gotrue)
                         ▼
     ┌───────────────────────────────────────────---┐
     │                  Supabase                    │
     │  ┌───────────────-┐  ┌──────────────────-─┐  │
     │  │  PostgreSQL    │  │   Auth (GoTrue)    │  │
     │  │  - Tables      │  │  - Sessions/JWT    │  │
     │  │  - RLS Policies│  │  - User identities │  │
     │  └───────────────-┘  └─────────────────-──┘  │
     │  ┌───────────────────────────────────────┐   │
     │  │           Storage (Attachments)       │   │
     │  └───────────────────────────────────────┘   │
     └──────────────────────────────────────────---─┘

     ┌───────────────────────────────────────────┐
     │        APScheduler (in-process)           │
     │        (src/scheduler)                    │
     │  - Escalation checks                      │
     │  - Reminder notifications                 │
     │  - Nightly analytics aggregation          │
     │  - Runs inside the same Python process,   │
     │    invoking Application Services directly │
     └───────────────────────────────────────────┘
```

Two notes on this diagram. First, APScheduler is drawn as a separate box because it operates on its own timers, but it is not a separate deployable — it lives inside the same process and calls the same Application Services layer as the UI. Second, the Workflow Engine is shown alongside the Domain layer because it depends on domain models but is invoked by Application Services rather than being a layer in its own right; it is a specialized component, described in Section 4.

---

## 3. Architectural Layers

EAH follows a strict top-down dependency rule: each layer may depend on the layer(s) beneath it, but never on the layer(s) above it. The Domain layer has no outward dependencies at all.

### 3.1 Presentation Layer (`src/ui`)

**Responsibility:** Render screens, collect user input, and display results. This layer contains Streamlit page functions, form widgets, and layout code.

The Presentation layer is intentionally "dumb." It does not perform validation beyond basic input constraints (e.g., disabling a submit button until required fields are filled), it does not talk to Supabase directly, and it does not contain business rules such as "an approval cannot be granted twice." Every meaningful action a user takes is delegated to a function in the Application layer, and the Presentation layer simply renders whatever typed result comes back (a Pydantic model, a list of models, or a raised, caught exception translated into a user-facing message).

This separation means the entire UI could be replaced (e.g., with a different Streamlit layout, or in principle a different framework) without touching business logic.

### 3.2 Application Layer (`src/services`)

**Responsibility:** Orchestrate use cases. Each service class exposes methods that correspond to a real-world action: `submit_request`, `approve_stage`, `add_comment`, `upload_attachment`, `record_audit_event`.

Application Services are the only components permitted to coordinate multiple repositories in a single logical operation (for example, `RequestService.submit_request` calls `RequestRepository` to insert the request, `WorkflowEngine` to determine the first approval stage, and `AuditService` to record the creation event). Services contain *orchestration* logic, not *domain* logic — they decide the order of operations, not the business rules themselves.

Services accept and return Pydantic models exclusively. They never accept or return raw dictionaries from Supabase responses; that translation happens in the Repository layer.

### 3.3 Domain Layer (`src/models`)

**Responsibility:** Define the shape and invariants of the data that flows through the system, using Pydantic v2 models.

This layer includes entities such as `Request`, `ApprovalStage`, `Comment`, `Attachment`, `AuditLogEntry`, `User`, and `NotificationEvent`, along with enums such as `RequestStatus` and `ApprovalDecision`. Validation rules that are intrinsic to the data itself (field length limits, required combinations of fields, enum membership) are enforced here via Pydantic validators, so that an invalid object simply cannot be constructed.

The Domain layer has zero dependencies on Streamlit, Supabase, or APScheduler. It is pure Python plus Pydantic, which makes it the most heavily unit-tested part of the codebase.

### 3.4 Repository Layer (`src/repositories`)

**Responsibility:** Translate between domain models and Supabase's data representation. Each repository wraps the Supabase Python client and exposes methods such as `get_by_id`, `list_for_user`, `insert`, `update_status`.

Repositories are the only place in the codebase where Supabase-specific query syntax appears. They are responsible for constructing parameterized queries, mapping raw rows into Pydantic models on the way out, and mapping Pydantic models into insert/update payloads on the way in. If Supabase's client library changes its API, only this layer needs to change.

### 3.5 Database Layer (Supabase / PostgreSQL)

**Responsibility:** Durable storage, identity management, and file storage.

This is not custom code but a managed platform. It is treated as an architectural layer because it enforces its own rules independently of the application: Row-Level Security policies restrict which rows a given authenticated user can read or write, foreign key constraints enforce referential integrity, and check constraints enforce database-level invariants (e.g., a status column restricted to a fixed set of values) as a second line of defense behind Pydantic validation.

---

## 4. Component Breakdown

**Authentication** — Wraps Supabase Auth (GoTrue) to handle sign-in, session refresh, and sign-out. Exposes a single `AuthService` used by the Streamlit session bootstrap to determine the current user and their role claim. No password handling, token issuance, or session storage is implemented manually; EAH consumes Supabase's JWTs and stores the session token in Streamlit's session state for the duration of the browser session.

**Workflow Engine** — A configuration-driven component (`src/workflows`) that determines, for a given request type, the ordered list of approval stages and the role or user responsible for each stage. Configuration is stored as structured JSON, loaded via the Configuration Loader, rather than hard-coded in Python, so new request types or approval chains can be added without code changes. The engine exposes a pure function-style API: given a request and its current stage, it returns the next stage or signals completion.

**Request Management** — The `RequestService` and associated repository handle the lifecycle of a request object: creation, retrieval, listing (filtered by requester, status, or assigned approver), and status transitions. This is the central entity around which most other components revolve.

**Approval Engine** — Distinct from the Workflow Engine: while the Workflow Engine defines *what stages exist and in what order*, the Approval Engine (`ApprovalService`) executes *the act of approving or rejecting* a specific stage instance, validates that the acting user is authorized for that stage, and hands control back to the Workflow Engine to determine the next step.

**Comment System** — `CommentService` and `CommentRepository` allow users to attach threaded remarks to a request. Comments are immutable once posted (edits are modeled as new comments referencing the original, not in-place mutation) to preserve an accurate history.

**Attachment System** — `AttachmentService` coordinates file uploads to Supabase Storage and stores file metadata (filename, size, content type, storage path, uploader) in PostgreSQL via `AttachmentRepository`. Files themselves never pass through the database; only references do.

**Audit Logging** — `AuditService` records an append-only entry for every state-changing action in the system (creation, approval, rejection, comment, attachment, status change). Audit entries are never updated or deleted by application code; the underlying table has no `UPDATE` or `DELETE` grants for the application role, only `INSERT` and `SELECT`.

**Notification Service** — `NotificationService` generates notification records (e.g., "your request was approved," "a request is awaiting your approval") and is invoked both synchronously (as part of a request's lifecycle) and asynchronously (by the Scheduler, for reminders and escalations). Every notification is persisted to a table and surfaced inside the Streamlit UI, and, as part of the baseline MVP, is also dispatched as an email via SMTP (using Python's standard `smtplib`/`email` libraries, with SMTP host, port, and credentials read through the Configuration Loader). In-app notification and email dispatch are two effects of the same call — a service consumer never invokes them separately, and a failure to send an email does not prevent the in-app notification record from being created. SMS delivery remains a described future extension, not part of the baseline.

**Scheduler** — Built on APScheduler, running as a background thread inside the same process as the Streamlit app. It implements the three background jobs required by the SRS:

- **Escalation Check** — runs on a configured interval (e.g., hourly) and flags requests whose current approval stage has been pending past a configured threshold, reassigning or notifying an escalation contact via `RequestService` and `NotificationService`.
- **Reminder Dispatch** — runs on a configured interval (e.g., daily) and sends reminder notifications, including email, to approvers with stages still awaiting their decision, via `NotificationService`.
- **Nightly Analytics Aggregation** — runs once per day and pre-computes aggregate figures (volumes, average approval time, completion rates) via `AnalyticsService` so dashboard loads do not require expensive on-demand aggregation.

All three jobs call into Application Services exactly the way the UI does — there is no separate code path for scheduled logic, and no job performs data access directly against a repository or the Supabase client.

**Analytics** — `AnalyticsService` (`src/analytics`) queries aggregated data (via repository methods or dedicated read-only queries) and prepares it for visualization. Rendering itself uses Plotly, invoked from the Presentation layer, but data shaping and aggregation logic lives in the Analytics component so it can be unit tested independently of any chart library.

**Configuration Loader** — A small, focused module responsible for loading environment variables (Supabase URL, Supabase keys, scheduler intervals, SMTP settings) and static JSON configuration files (workflow definitions) into typed Pydantic settings objects at startup. All other components read configuration exclusively through this loader; no component reads `os.environ` directly, and no other configuration format (e.g., YAML) is introduced into the codebase.

**Validation Layer** — Not a separate folder but a cross-cutting discipline implemented primarily through Pydantic v2 models and validators in the Domain layer, supplemented by explicit guard clauses in Application Services for rules that depend on database state (e.g., "a stage cannot be approved twice"), which cannot be expressed as a static model constraint.

---

## 5. Request Lifecycle

The following sequence describes the full path of a single request from creation to completion.

```
1. User opens form
   └─ Streamlit renders a request-submission page (src/ui)
      Fields are bound to a draft Pydantic model as the user types.

2. Client-side shape validation
   └─ On submit, the UI attempts to construct a Request model.
      Pydantic v2 raises a ValidationError if required fields are
      missing or malformed; the UI displays these inline and halts.

3. Application layer invocation
   └─ RequestService.submit_request(request: RequestCreate, user: User)
      is called with a validated model — never raw form data.

4. Business rule validation (fail fast)
   └─ RequestService checks state-dependent rules the model alone
      cannot express (e.g., duplicate submission window, requester
      eligibility for this request type). Violations raise a
      domain-specific exception before anything is persisted.

5. Database transaction
   └─ RequestRepository.insert() writes the new request row.
      Where multiple related rows must be written together
      (e.g., request + initial approval stage), the repository
      uses a single Supabase RPC/transaction to keep them atomic.

6. Workflow assignment
   └─ WorkflowEngine.get_initial_stage(request) resolves the
      configured approval chain for this request type and
      determines the first responsible approver or role.
      ApprovalRepository creates the corresponding stage row.

7. Audit logging
   └─ AuditService.record_event() writes an immutable log entry:
      actor, action ("REQUEST_CREATED"), timestamp, and a snapshot
      of relevant request fields.

8. Notification
   └─ NotificationService.notify() creates a notification record
      for the assigned approver, surfaced in their UI on next load
      or next scheduler-driven refresh.

9. Approval
   └─ The approver opens the Approvals page, reviews the request,
      comments if needed (CommentService), and calls
      ApprovalService.decide(stage_id, decision, user).
      The Approval Engine validates authorization, updates the
      stage, logs an audit event, and asks the Workflow Engine
      whether further stages remain.

10. Completion
    └─ If no further stages remain, RequestService marks the
       request as COMPLETED (or REJECTED), a final audit entry is
       recorded, and a completion notification is sent to the
       original requester. If stages remain, control returns to
       step 8 for the next approver.
```

Every step above is expressed as a plain function call between layers; there is no queue, no message broker, and no asynchronous boundary except the Scheduler's own timer loop, which is described separately in Section 4.

---

## 6. Folder Responsibilities

```
src/
├── ui/            Streamlit pages, forms, layout, and session-state glue.
│                  Depends on: services. Never imports repositories directly.
│
├── services/      Application layer. Orchestrates use cases by calling
│                  domain models, workflows, and repositories together.
│                  Depends on: models, workflows, repositories.
│
├── models/        Domain layer. Pydantic v2 models, enums, and value
│                  objects that define valid data shapes and invariants.
│                  Depends on: nothing internal (pure Python + Pydantic).
│
├── repositories/  Data access layer. Wraps the Supabase client; the only
│                  place SQL/PostgREST query syntax and storage-bucket
│                  calls appear. Maps between rows and domain models.
│                  Depends on: models, the Supabase client.
│
├── workflows/     Configuration-driven workflow/approval-chain logic.
│                  Determines stage ordering and assignment rules.
│                  Depends on: models, configuration loader.
│
├── scheduler/     APScheduler job definitions and startup wiring for
│                  background tasks (escalations, reminders, nightly
│                  aggregation). Calls into services, nothing else.
│
├── analytics/     Aggregation and data-shaping logic feeding Plotly
│                  visualizations rendered by the UI layer.
│                  Depends on: repositories, models.
│
└── utils/         Small, stateless cross-cutting helpers (date/time
                   formatting, ID generation, logging setup, the
                   configuration loader). No business logic lives here.
```

No folders beyond these are introduced. Cross-cutting concerns that do not fit neatly (such as configuration loading) are placed in `utils` rather than spawning a new top-level package, keeping the structure flat and predictable.

---

## 7. Design Principles

**Single Responsibility Principle.** Every class in `services/` corresponds to exactly one area of the domain (requests, approvals, comments, attachments, audit, notifications, analytics, auth). A change to how comments are stored should never require touching `RequestService`.

**Separation of Concerns.** Enforced structurally by the layering itself: presentation code cannot see the database client, and repository code cannot see Streamlit. This is not a convention enforced by discipline alone — repositories simply do not import `streamlit`, and UI modules do not import the Supabase client, which makes violations easy to spot in code review.

**Repository Pattern.** All persistence operations are mediated by repository classes with narrow, intention-revealing method names (`get_pending_for_approver`, not a leaked raw query). This makes it possible to write fast unit tests for services using in-memory fake repositories that satisfy the same interface, without touching Supabase at all.

**Dependency Injection (where appropriate).** EAH uses lightweight constructor injection: services receive their repository instances as constructor arguments rather than instantiating a Supabase client internally. This is a deliberately modest form of DI — plain Python, no framework — sufficient for swapping real repositories for test doubles in pytest without introducing a DI container, which would be disproportionate for an application of this size.

**Immutable Audit Logs.** Audit entries are append-only by construction: the database role used by the application has `INSERT`/`SELECT` privileges on the audit table but not `UPDATE`/`DELETE`, and no service method exists to modify a logged entry. History, once recorded, cannot be silently altered.

**Configuration-Driven Workflows.** Approval chains are data, not code. Adding a new request type with a different approval sequence means adding a configuration entry, not writing a new Python class, which keeps the Workflow Engine stable while the set of supported workflows grows.

**Type Safety.** Pydantic v2 models are the single source of truth for data shape throughout the application. Type hints are used consistently across services and repositories, allowing static analysis tools (mypy, in CI) to catch an entire class of bugs before runtime.

**Fail Fast Validation.** Invalid data is rejected as early as possible — at model construction, before it reaches a service, and certainly before it reaches the database. A malformed request is never allowed to travel deeper into the system than necessary to detect the problem.

---

## 8. Error Handling Strategy

**Validation errors.** Pydantic's `ValidationError` is caught at the UI boundary (where user-submitted data is first parsed into a model) and translated into field-level error messages. Application Services may additionally raise custom exceptions (e.g., `DuplicateRequestError`, `InvalidStageTransitionError`) for rules that require database state to evaluate; these are caught at the same UI boundary and rendered as clear, non-technical messages.

**Database failures.** Repository methods catch exceptions raised by the Supabase client (network errors, constraint violations) and re-raise them as a small set of internal exception types (`RepositoryError`, `RecordNotFoundError`, `ConstraintViolationError`) so that the Application layer and UI never need to know about the underlying HTTP/PostgREST error shape. Transient failures (timeouts) are retried a bounded number of times at the repository boundary; persistent failures propagate as `RepositoryError` and are surfaced to the user as a generic "unable to complete this action, please try again" message, with full details captured in logs.

**Authentication failures.** Handled by `AuthService`; an expired or invalid session results in the user being redirected to the login page rather than the application attempting to reason about a half-authenticated state.

**Permission failures.** Distinct from authentication: a user may be authenticated but not authorized for a specific action (e.g., approving a stage assigned to someone else). These are enforced twice — once in the Application layer (explicit role/ownership checks before any mutation) and once at the database level via Row-Level Security, so that a bug in application-level checks cannot by itself result in unauthorized data access.

**Unexpected exceptions.** A top-level exception boundary in the Streamlit entry point catches anything not already handled, logs the full stack trace with request context, and shows the user a generic error message. The application never displays raw stack traces or internal exception messages in the UI.

**Logging philosophy.** EAH uses Python's standard `logging` module, configured once at startup via the Configuration Loader. Logs are structured (consistent key fields: timestamp, user id, action, outcome) so they can be searched or piped into a log aggregator later without changing application code. Logging is treated as an operational concern separate from the immutable audit log described in Section 4: logs are for operators, audit entries are for compliance/history and are part of the domain model itself.

---

## 9. Security Architecture

**Supabase Authentication.** All user identity is delegated to Supabase Auth. EAH does not store passwords, does not implement its own token issuance, and does not maintain a parallel identity table beyond a `profiles` table that extends Supabase's built-in `auth.users` with application-specific fields (role, department).

**Role-Based Access Control.** Each user has a role (e.g., `employee`, `approver`, `admin`) stored in the `profiles` table and included as a custom claim retrievable from the authenticated session. Application Services check this role before allowing role-sensitive actions (approving a stage, viewing administrative analytics, modifying workflow configuration).

**Row-Level Security.** RLS policies are defined directly in PostgreSQL and serve as the authoritative enforcement layer, independent of application code correctness. Representative policies:
- A user may `SELECT` a request row only if they are the requester, the currently assigned approver, or hold the `admin` role.
- A user may `INSERT` into the approvals table only for a stage where they are the assigned approver.
- A user may never directly `UPDATE` or `DELETE` audit log rows, regardless of role.

**Environment Variables.** Supabase URL, the anon key, the service-role key (used only by trusted server-side/scheduler code, never exposed to the browser), and scheduler intervals are loaded from environment variables through the Configuration Loader at startup. Secrets are never hard-coded and never logged.

**Input Validation.** Every external input — form fields, uploaded file metadata, query parameters — passes through a Pydantic model before it reaches any service or repository, closing off an entire class of injection and malformed-data issues at the boundary.

**Parameterized Queries.** All database access goes through the Supabase client library, which parameterizes query values; no application code constructs SQL by string concatenation or interpolation.

**Secure File Uploads.** `AttachmentService` enforces an allow-list of file extensions and a maximum file size before handing the file to Supabase Storage, stores files under a path namespaced by request id (preventing path traversal or collision), and persists only a storage reference plus metadata in PostgreSQL — the file content itself never passes through application memory longer than necessary for the upload call.

---

## 10. Scalability Considerations

EAH scales as a monolith along three independent axes, without introducing additional services:

**Vertical and read scaling of Supabase.** Supabase's managed PostgreSQL can be scaled vertically (larger compute/memory tier) as data volume grows, and read-heavy workloads (analytics queries, dashboard loads) can be offloaded to Postgres read replicas where Supabase's plan supports them, without any change to application code beyond configuring a read-preferring connection where appropriate.

**Stateless horizontal scaling of the Streamlit process.** Because all durable state lives in Supabase and Streamlit session state holds only transient UI/session data, multiple instances of the EAH application can run behind a standard load balancer. A user's request-handling does not depend on which instance served their previous interaction, aside from their authenticated session token, which Supabase Auth manages independently of any single application instance.

**Workload separation within the process.** APScheduler jobs are configured with bounded concurrency and can be tuned or disabled per deployment (for instance, running only on one designated instance in a multi-instance deployment, using a simple leader flag in configuration) so that background aggregation and escalation checks do not compete for resources with interactive user requests.

**Code-level scalability.** Because business logic lives in the Application and Domain layers, independent of Streamlit, the same services could in the future be reused behind a different or additional interface (a CLI, a lightweight REST layer for integrations) without duplicating logic — the monolith's internal modularity is what enables this, not a change in deployment topology.

Scaling further than this (e.g., true multi-region active-active writes, sharding) is explicitly out of scope for the intended use case and would represent a deliberate architectural pivot away from a modular monolith, not an incremental step within it.

---

## 11. Architectural Decisions

| Decision | Reason | Trade-off |
|---|---|---|
| Use Streamlit as the sole UI framework | Fast to build data-centric internal tools with a small team; native Python, no separate frontend build | Limited control over fine-grained UI/UX compared to a dedicated JS frontend |
| Use Supabase for database, auth, and storage | Consolidates three infrastructure concerns behind one managed platform, reducing operational burden for a solo developer | Some vendor lock-in to Supabase-specific client APIs and RLS conventions |
| Adopt a layered modular monolith instead of microservices | Matches the scale of the project and avoids operational overhead disproportionate to a single-team application | Cannot scale individual components independently without future refactoring |
| Use Pydantic v2 for all data contracts | Enforces type safety and fail-fast validation at every layer boundary | Adds a small amount of boilerplate for model definitions |
| Enforce RLS at the database in addition to application checks | Provides defense-in-depth; a bug in service-layer authorization does not expose data | Policy logic must be maintained in two places (SQL and Python) |
| Use APScheduler in-process rather than an external task queue | Avoids introducing Celery/Redis/RabbitMQ for a workload that is periodic, not high-throughput | Scheduler is tied to the application process lifecycle; no independent scaling of background jobs |
| Store workflow definitions as configuration rather than code | Allows new approval chains without redeploying application logic | Requires a schema/format for configuration and validation of that configuration itself |
| Make audit logs append-only at the database grant level | Guarantees historical integrity independent of application bugs | Requires a separate mechanism (not implemented here) for legitimate log retention/archival policy |
| Pair in-app notifications with SMTP email delivery in the MVP, but exclude SMS | Ensures approvers and requesters are reliably reached without introducing infrastructure beyond the required stack (SMTP via Python's standard library) | Requires SMTP configuration and credential management; email delivery failures must be handled without blocking in-app notification |
| Use constructor-based dependency injection instead of a DI framework | Sufficient for testability at this scale without added complexity | Wiring is manual; would need reconsideration if the object graph grows significantly |

---

## 12. Future Evolution

The architecture is deliberately positioned so that several plausible future requirements can be absorbed without restructuring the core layers:

**Additional notification channels** (SMS, push, or webhook-based integrations, or replacing direct SMTP with a transactional email provider) can be added as new methods on `NotificationService` without touching Request, Approval, or Audit logic, since those components already depend only on the `NotificationService` interface, not its delivery mechanism.

**A REST or CLI interface alongside Streamlit** is possible because the Application layer never depends on Streamlit; a new thin entry point could call the same `services/` classes directly.

**More granular RBAC** (per-department or per-workflow permissions) can be layered onto the existing role-check pattern in both application code and RLS policies without changing the shape of the Domain layer.

**Read-scaling of analytics** by introducing materialized views or a dedicated read replica in Supabase can be adopted transparently behind `AnalyticsService`, since UI code never queries the database directly.

**Multi-tenancy**, if ever required, would extend existing RLS policies and add a tenant identifier to relevant models and tables, following the same enforcement pattern already established for user- and role-based access — a data-model extension rather than an architectural rewrite.

None of these evolutions require introducing the technologies explicitly excluded from this architecture. The modular monolith is expected to remain the correct shape for this application through several iterations of feature growth.