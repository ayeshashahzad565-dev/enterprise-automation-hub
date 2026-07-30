# Enterprise Automation Hub (EAH)
## Database Schema Design Document

**Version:** 1.1
**Status:** Production-Hardened Schema — consistent with the finalized SRS and Architecture Design Document (ADD)
**Author:** Principal Database Architect
**Platform:** Supabase (PostgreSQL, Auth, Storage)

> **Superseded note:** The schema below is unaffected by the later
> Presentation Layer rewrite (Streamlit → FastAPI + Next.js) and remains
> an accurate description of the live database. Two details in Section
> 9.3 below are now stale: the application-process description ("the
> Python process running Streamlit and APScheduler" now applies to the
> FastAPI process, `app/`, still running APScheduler in-process — see
> `docs/deployment.md` for the current process topology), and the claim
> that the service-role key is used "exclusively" server-side — a
> verified subset of repositories now instead run under a per-request,
> caller-scoped client so RLS is actually enforced for them. See
> `docs/tenant_isolation.md` for exactly which, why, and how the rest are
> hardened differently.

---

## 1. Database Overview

This document describes the relational schema that backs the Enterprise Automation Hub, as implemented on Supabase's managed PostgreSQL platform. It is written to be read alongside the Architecture Design Document (ADD): the Repository Layer described there is the only application code that touches these tables directly, and every table below maps to one or more repository classes in `src/repositories`.

### 1.1 Why PostgreSQL

PostgreSQL was selected as the system of record for three reasons that follow directly from the requirements in the SRS:

- **Strong relational integrity.** Requests, approval stages, comments, attachments, and audit entries are all related records with strict referential rules (an approval stage cannot exist without a request, a comment cannot exist without both a request and an author). PostgreSQL's foreign key constraints enforce these rules at the database level as a second line of defense behind Pydantic validation in the application.
- **Native JSON support.** The SRS requires workflow definitions to be stored as JSON. PostgreSQL's `jsonb` type stores this JSON in a binary, indexable form, which is queryable with native operators rather than requiring the JSON to be treated as an opaque blob.
- **Row-Level Security (RLS).** PostgreSQL's RLS mechanism allows authorization rules (submitter, approver, administrator) to be enforced directly on the database connection used by Supabase's client libraries, independent of whether the application code correctly re-checks permissions. This gives the system defense-in-depth, as described in Section 9.

### 1.2 Why Supabase

Supabase was selected because it packages exactly the three infrastructure concerns EAH requires — a managed PostgreSQL instance, an authentication provider (GoTrue), and object storage — behind a single platform, with client libraries that integrate cleanly with the Repository Layer described in the ADD. This avoids operating separate infrastructure for identity and file storage, which would be disproportionate for a solo-developer, modular-monolith project. No infrastructure outside Supabase, PostgreSQL, and the application's own Python process is introduced by this schema.

### 1.3 Normalization Goals

The schema is normalized to Third Normal Form (3NF) for all transactional tables. Each table represents exactly one entity from the domain model described in the ADD (`Request`, `ApprovalStage`, `Comment`, `Attachment`, `AuditLogEntry`, `User`/`Profile`, `NotificationEvent`), and no column stores data derivable from other columns in the same row. The single deliberate departure from strict normalization is the `workflow_definitions.definition` column, which stores a structured JSON document rather than being decomposed into further tables. This is a considered exception, not an oversight, and is justified in full in Section 5.

### 1.4 Transactional Consistency

Every operation that must leave the database in a single coherent state is executed as a single PostgreSQL transaction, issued from the Repository Layer. The application never relies on eventual consistency between related tables: a request and its first approval stage are created together or not at all, an approval decision and its audit log entry are written together or not at all. Section 11 enumerates the specific operations that require transactional boundaries and explains why.

### 1.5 Native PostgreSQL ENUM Types

Columns that previously would have been described as `text` with an implied set of allowed values (`profiles.role`, `requests.status`, `workflow_stages.status`, `notifications.notification_type`) are instead implemented as native PostgreSQL `ENUM` types. This is a refinement of representation, not of the underlying domain model already described in the ADD — the same Pydantic enums in `src/models` continue to be the application-level source of truth; the database-level type now mirrors them exactly rather than approximating them with a `CHECK` constraint.

**Why native ENUMs over `TEXT` + `CHECK`:**

- **Storage efficiency.** A PostgreSQL `ENUM` is stored internally as a 4-byte value, rather than as variable-length text, which is a meaningful saving across high-volume tables such as `workflow_stages` and `notifications`.
- **Faster comparisons and sorting.** Enum values compare and sort according to the order they were declared in, using simple integer comparison internally, rather than text collation rules.
- **Self-documenting schema.** The set of valid values is a first-class database object (visible via `\dT+` or the system catalogs), rather than logic buried inside a `CHECK` constraint expression that must be located and read separately.
- **Centralized change management.** Adding a new valid value is a single, explicit `ALTER TYPE ... ADD VALUE` statement against the type itself, rather than a `CHECK` constraint that must be dropped and recreated across every table that repeats the same list of allowed values.

**Enum types used in this schema:**

| Enum Type | Values | Used By |
|---|---|---|
| `user_role` | `employee`, `approver`, `admin` | `profiles.role` |
| `request_status` | `pending`, `in_review`, `approved`, `rejected`, `completed` | `requests.status` |
| `stage_status` | `pending`, `approved`, `rejected`, `skipped` | `workflow_stages.status` |
| `notification_type` | `assignment`, `reminder`, `escalation`, `decision`, `completion`, `system` | `notifications.notification_type` |

Example type definition, illustrating the intended shape (documentation only, not a migration script):

```sql
CREATE TYPE request_status AS ENUM (
    'pending',
    'in_review',
    'approved',
    'rejected',
    'completed'
);
```

Table specifications in Section 3 reference these enum types by name rather than repeating `text (enum: ...)` inline.

### 1.6 UUID Generation

Every primary key in this schema is a `uuid`, generated by PostgreSQL itself rather than by application code. Supabase provisions the `pgcrypto` extension on every project by default, and `gen_random_uuid()` — referenced throughout Section 3 as a column default — is the function this extension provides. Because generation happens inside PostgreSQL at insert time, the Repository Layer never constructs identifiers in Python; it simply omits the `id` column on insert and reads back the generated value, which keeps identifier generation a single, database-owned concern rather than a duplicated responsibility across the codebase.

---

## 2. Entity Relationship Overview

### 2.1 Tables

| Table | Represents | Owned By (Domain Model) |
|---|---|---|
| `auth.users` | Supabase-managed identity record (email, hashed credential, session metadata) | Managed entirely by Supabase Auth; not modified by application code |
| `profiles` | Application-specific extension of a user's identity (role, department, display name) | `User` |
| `workflow_definitions` | A versioned, JSON-encoded definition of an approval chain for a request type | Consumed by the Workflow Engine |
| `requests` | A single business request submitted by an employee | `Request` |
| `workflow_stages` | A single approval step within a specific request's lifecycle | `ApprovalStage` |
| `comments` | A threaded remark attached to a request | `Comment` |
| `attachments` | Metadata for a file uploaded against a request | `Attachment` |
| `notifications` | An in-app (and email-mirrored) notification directed at a user | `NotificationEvent` |
| `audit_logs` | An immutable, append-only record of a state-changing action | `AuditLogEntry` |

### 2.2 Relationship Summary

```
auth.users (1) ──── (1) profiles
profiles   (1) ──── (M) requests            [requester_id]
profiles   (1) ──── (M) workflow_stages      [assigned_user_id, nullable]
profiles   (1) ──── (M) comments             [author_id]
profiles   (1) ──── (M) attachments          [uploaded_by]
profiles   (1) ──── (M) notifications        [recipient_id]
profiles   (1) ──── (M) audit_logs           [actor_id, nullable]

workflow_definitions (1) ──── (M) requests   [workflow_definition_id]

requests   (1) ──── (M) workflow_stages      [request_id]
requests   (1) ──── (M) comments             [request_id]
requests   (1) ──── (M) attachments          [request_id]
requests   (1) ──── (0..M) notifications     [request_id, nullable]
requests   (1) ──── (0..M) audit_logs        [request_id, nullable]

comments   (1) ──── (0..M) comments          [parent_comment_id — self-referencing thread]
```

### 2.3 Cardinality Notes

- A **profile** corresponds to exactly one **auth.users** record (1:1), created automatically when a user first authenticates.
- A **request** belongs to exactly one requester but may accumulate many **workflow_stages**, **comments**, and **attachments** (1:M in each case).
- A **workflow_definition** may be referenced by many **requests** over time (1:M), since the same approval chain applies to every request of a given type and version.
- A **workflow_stage** is assigned to at most one specific user at a time (0..1), or left assigned to a role until claimed, depending on configuration (see Section 5).
- A **comment** may optionally reference a parent comment to support threaded replies (0..1 self-referencing relationship).
- **notifications** and **audit_logs** optionally reference a request (`request_id` is nullable) because some notifications and audit entries are system-level (e.g., "workflow definition updated") rather than tied to a specific request.

---

## 3. Table Specifications

### 3.1 `profiles`

**Purpose:** Extends `auth.users` with application-specific identity attributes required for authorization and display, without duplicating anything Supabase Auth already manages (email, password, session tokens).

| Column | Type | Nullable | Default | Description |
|---|---|---|---|---|
| `id` | `uuid` | No | — | Primary key; equal to the corresponding `auth.users.id` |
| `full_name` | `text` | No | — | Display name shown throughout the UI |
| `role` | `user_role` (native ENUM — see Section 1.5) | No | `'employee'` | RBAC role used by application checks and RLS policies |
| `department` | `text` | Yes | `NULL` | Organizational department, used for filtering and analytics |
| `version` | `integer` | No | `1` | Row version used for optimistic concurrency control (see Section 3.9) |
| `created_at` | `timestamptz` | No | `now()` | Record creation timestamp |
| `updated_at` | `timestamptz` | No | `now()` | Last modification timestamp |
| `is_active` | `boolean` | No | `true` | Whether this profile may currently authenticate (`0020_profile_lifecycle`) — reversible deactivation, checked on every request |
| `deleted_at` | `timestamptz` | Yes | `NULL` | When this profile was erased (GDPR right-to-erasure), if ever — see Section 3.10 |
| `deleted_by` | `uuid` | Yes | `NULL` | The admin who performed the erasure, if any |

- **Primary Key:** `id`
- **Foreign Keys:** `id` references `auth.users.id`; `deleted_by` references `profiles.id` (self-referencing, `ON DELETE SET NULL`)
- **Unique Constraints:** `id` (implicit via primary key / 1:1 relationship)
- **Indexes:** index on `role`; index on `department`; index on `deleted_at` (backs the `deleted_at IS NULL` default filter every listing method applies)
- **Business Rules:** A `profiles` row is created automatically the first time a user authenticates (via a Supabase trigger on `auth.users`, described only at the architectural level here, not as SQL). `role` may only be changed by an `admin`. Updates to `role`, `department`, or `is_active` are performed under optimistic locking, per Section 3.9. Erasure (`deleted_at`/`deleted_by`) is irreversible and additionally overwrites `full_name`/`department` — see Section 3.10.

### 3.2 `workflow_definitions`

**Purpose:** Stores the versioned, JSON-encoded configuration that the Workflow Engine uses to determine the ordered list of approval stages for a given request type.

| Column | Type | Nullable | Default | Description |
|---|---|---|---|---|
| `id` | `uuid` | No | `gen_random_uuid()` | Primary key |
| `request_type` | `text` | No | — | Identifier for the request type this definition governs (e.g., `expense_reimbursement`) |
| `version` | `integer` | No | `1` | Monotonically increasing version number for this `request_type` (business version, distinct from the concurrency `row_version` below) |
| `definition` | `jsonb` | No | — | The structured JSON document describing stages and assignment rules (see Section 5) |
| `is_active` | `boolean` | No | `true` | Whether this version is the one currently used for new requests of this type |
| `created_by` | `uuid` | No | — | The administrator who authored this version |
| `row_version` | `integer` | No | `1` | Row version used for optimistic concurrency control on `is_active` toggles (see Section 3.9) |
| `created_at` | `timestamptz` | No | `now()` | Record creation timestamp |

- **Primary Key:** `id`
- **Foreign Keys:** `created_by` references `profiles.id`
- **Unique Constraints:** unique on (`request_type`, `version`)
- **Indexes:** index on `request_type`; partial index on `is_active` where `is_active = true`
- **Check Constraints:** `version > 0` (see Section 4.1)
- **Business Rules:** Only one `(request_type, is_active = true)` combination may exist at a time; activating a new version deactivates the prior one within the same transaction. Existing `requests` retain a reference to the specific version they were created under, so editing or deactivating a definition never changes the approval chain of a request already in flight.

### 3.3 `requests`

**Purpose:** The central entity of the system — a single business request submitted by an employee and tracked through to completion.

| Column | Type | Nullable | Default | Description |
|---|---|---|---|---|
| `id` | `uuid` | No | `gen_random_uuid()` | Primary key |
| `requester_id` | `uuid` | No | — | The user who submitted the request |
| `workflow_definition_id` | `uuid` | No | — | The specific workflow definition version governing this request |
| `request_type` | `text` | No | — | Denormalized copy of the request type, for fast filtering without a join |
| `title` | `text` | No | — | Short human-readable summary |
| `description` | `text` | Yes | `NULL` | Full request details |
| `department` | `text` | Yes | `NULL` | Department the request was raised under |
| `status` | `request_status` (native ENUM — see Section 1.5) | No | `'pending'` | Current lifecycle status |
| `current_stage_id` | `uuid` | Yes | `NULL` | The `workflow_stages` row currently awaiting action, if any |
| `version` | `integer` | No | `1` | Row version used for optimistic concurrency control (see Section 3.9) |
| `deleted_at` | `timestamptz` | Yes | `NULL` | Soft-deletion timestamp; `NULL` for an active request (see Section 3.10) |
| `deleted_by` | `uuid` | Yes | `NULL` | The administrator who withdrew/removed the request, if soft-deleted |
| `created_at` | `timestamptz` | No | `now()` | Submission timestamp |
| `updated_at` | `timestamptz` | No | `now()` | Last modification timestamp |
| `completed_at` | `timestamptz` | Yes | `NULL` | Timestamp of final approval, rejection, or completion |

- **Primary Key:** `id`
- **Foreign Keys:** `requester_id` references `profiles.id`; `workflow_definition_id` references `workflow_definitions.id`; `current_stage_id` references `workflow_stages.id` (nullable, deferrable — see Section 4); `deleted_by` references `profiles.id`
- **Unique Constraints:** none beyond the primary key
- **Indexes:** index on `status`; index on `request_type`; index on `created_at`; index on `department`; index on `requester_id` (see Section 10 for composite indexes built on these columns)
- **Check Constraints:** `completed_at >= created_at` where `completed_at` is not `NULL` (see Section 4.1)
- **Business Rules:** `status` transitions are enforced by the Application layer (Workflow Engine and Approval Engine), not by a database trigger, consistent with the ADD's decision to keep business rules in Python; the database enforces only that `status` is one of the allowed `request_status` enum values. Updates to `status`, `current_stage_id`, or `department` are performed under optimistic locking against `version` (Section 3.9). A request that has been withdrawn or administratively removed is soft-deleted (`deleted_at`/`deleted_by` populated) rather than hard-deleted, consistent with Section 3.10 and the `RESTRICT` behaviors in Section 4.

### 3.4 `workflow_stages`

**Purpose:** Represents a single approval step within a specific request's lifecycle — the runtime instantiation of one entry in a `workflow_definitions.definition` document.

| Column | Type | Nullable | Default | Description |
|---|---|---|---|---|
| `id` | `uuid` | No | `gen_random_uuid()` | Primary key |
| `request_id` | `uuid` | No | — | The request this stage belongs to |
| `stage_order` | `integer` | No | — | Position of this stage within the approval chain (1-indexed) |
| `stage_name` | `text` | No | — | Human-readable stage label (e.g., "Manager Review") |
| `assigned_role` | `text` | Yes | `NULL` | Role eligible to act on this stage, if not assigned to a specific user |
| `assigned_to` | `uuid` | Yes | `NULL` | Specific user assigned to this stage, if resolved |
| `status` | `stage_status` (native ENUM — see Section 1.5) | No | `'pending'` | Current status of this stage |
| `decided_by` | `uuid` | Yes | `NULL` | The user who made the approval decision |
| `decided_at` | `timestamptz` | Yes | `NULL` | Timestamp of the decision |
| `decision_note` | `text` | Yes | `NULL` | Optional note provided at the time of decision |
| `version` | `integer` | No | `1` | Row version used for optimistic concurrency control (see Section 3.9) |
| `created_at` | `timestamptz` | No | `now()` | Stage creation timestamp |

- **Primary Key:** `id`
- **Foreign Keys:** `request_id` references `requests.id`; `assigned_to` references `profiles.id`; `decided_by` references `profiles.id`
- **Unique Constraints:** unique on (`request_id`, `stage_order`)
- **Indexes:** index on `request_id`; index on `status`; index on `assigned_to` (see Section 10 for composite indexes built on these columns)
- **Check Constraints:** `stage_order > 0` (see Section 4.1)
- **Business Rules:** A stage's `status` may only move from `pending` to `approved`, `rejected`, or `skipped` — never backward — and this transition is validated by the Approval Engine before the update is issued. A stage cannot be decided twice; the Application layer checks `status = 'pending'` before accepting a decision, and this is additionally protected by RLS (Section 9) and by optimistic locking on `version` (Section 3.9), which rejects a concurrent decision attempt against a stale row.

### 3.5 `comments`

**Purpose:** A threaded remark attached to a request, used by requesters, approvers, and administrators to provide context during review.

| Column | Type | Nullable | Default | Description |
|---|---|---|---|---|
| `id` | `uuid` | No | `gen_random_uuid()` | Primary key |
| `request_id` | `uuid` | No | — | The request this comment is attached to |
| `author_id` | `uuid` | No | — | The user who wrote the comment |
| `parent_comment_id` | `uuid` | Yes | `NULL` | The comment this one replies to, if any |
| `body` | `text` | No | — | Comment content |
| `deleted_at` | `timestamptz` | Yes | `NULL` | Soft-deletion timestamp, for administrative removal of inappropriate content (see Section 3.10) |
| `deleted_by` | `uuid` | Yes | `NULL` | The administrator who removed the comment, if soft-deleted |
| `created_at` | `timestamptz` | No | `now()` | Comment creation timestamp |

- **Primary Key:** `id`
- **Foreign Keys:** `request_id` references `requests.id`; `author_id` references `profiles.id`; `parent_comment_id` references `comments.id` (self-referencing); `deleted_by` references `profiles.id`
- **Unique Constraints:** none
- **Indexes:** index on `request_id`; index on `parent_comment_id`
- **Business Rules:** Comments are immutable once created, consistent with the ADD's Comment System design — there is no `updated_at` column and no in-place edit path in the Repository Layer. A correction is modeled as a new comment referencing the original via `parent_comment_id`, never as an in-place edit. Administrative removal (e.g., inappropriate content) is a soft delete (`deleted_at`/`deleted_by`), never a hard delete, so the comment continues to satisfy its audit and thread-integrity obligations.

### 3.6 `attachments`

**Purpose:** Stores metadata describing a file uploaded against a request. The file content itself resides in Supabase Storage, not in PostgreSQL (see Section 7).

| Column | Type | Nullable | Default | Description |
|---|---|---|---|---|
| `id` | `uuid` | No | `gen_random_uuid()` | Primary key |
| `request_id` | `uuid` | No | — | The request this attachment belongs to |
| `uploaded_by` | `uuid` | No | — | The user who uploaded the file |
| `file_name` | `text` | No | — | Original filename as provided by the uploader |
| `content_type` | `text` | No | — | MIME type, validated against an allow-list before upload |
| `size_bytes` | `bigint` | No | — | File size, validated against a configured maximum before upload |
| `storage_path` | `text` | No | — | Path within the Supabase Storage bucket (see Section 7 for convention) |
| `deleted_at` | `timestamptz` | Yes | `NULL` | Soft-deletion timestamp; metadata is retained after removal (see Section 3.10) |
| `deleted_by` | `uuid` | Yes | `NULL` | The user who removed the attachment, if soft-deleted |
| `created_at` | `timestamptz` | No | `now()` | Upload timestamp |

- **Primary Key:** `id`
- **Foreign Keys:** `request_id` references `requests.id`; `uploaded_by` references `profiles.id`; `deleted_by` references `profiles.id`
- **Unique Constraints:** unique on `storage_path`
- **Indexes:** index on `request_id`
- **Check Constraints:** `size_bytes > 0` (see Section 4.1)
- **Business Rules:** A row is only inserted after the corresponding object has been successfully written to Supabase Storage, so that `attachments` never references a nonexistent file (see the transactional discussion in Section 11). Removing an attachment is a soft delete: the metadata row is retained (`deleted_at`/`deleted_by` populated) even after the underlying Storage object is removed, so that audit and comment context referencing the upload remain resolvable.

### 3.7 `notifications`

**Purpose:** Represents an in-app notification directed at a user, optionally mirrored as an email, as described in the ADD's Notification Service.

| Column | Type | Nullable | Default | Description |
|---|---|---|---|---|
| `id` | `uuid` | No | `gen_random_uuid()` | Primary key |
| `recipient_id` | `uuid` | No | — | The user this notification is directed at |
| `request_id` | `uuid` | Yes | `NULL` | The related request, if any |
| `notification_type` | `notification_type` (native ENUM — see Section 1.5) | No | — | Category of notification |
| `message` | `text` | No | — | Notification body shown in the UI |
| `is_read` | `boolean` | No | `false` | Whether the recipient has viewed the notification |
| `read_at` | `timestamptz` | Yes | `NULL` | Timestamp the notification was marked read |
| `email_sent` | `boolean` | No | `false` | Whether the corresponding email was successfully dispatched |
| `email_sent_at` | `timestamptz` | Yes | `NULL` | Timestamp of successful email dispatch |
| `archived_at` | `timestamptz` | Yes | `NULL` | Timestamp the recipient archived this notification, removing it from their default view (added by this application's notification-management UX build-out — see Section 8.5) |
| `created_at` | `timestamptz` | No | `now()` | Notification creation timestamp |

- **Primary Key:** `id`
- **Foreign Keys:** `recipient_id` references `profiles.id`; `request_id` references `requests.id`
- **Unique Constraints:** none
- **Indexes:** index on `recipient_id`; index on `is_read`; index on `request_id`; index on `created_at`; composite index on (`recipient_id`, `archived_at`)
- **Business Rules:** `email_sent` failing to become `true` never blocks or reverses the creation of the in-app row — the two effects are independent, consistent with the ADD's description of the Notification Service.

### 3.8 `audit_logs`

**Purpose:** An immutable, append-only record of every state-changing action in the system, used for historical accountability rather than operational logging.

| Column | Type | Nullable | Default | Description |
|---|---|---|---|---|
| `id` | `uuid` | No | `gen_random_uuid()` | Primary key |
| `actor_id` | `uuid` | Yes | `NULL` | The user who performed the action (`NULL` for system-initiated actions, e.g., scheduler escalations) |
| `request_id` | `uuid` | Yes | `NULL` | The related request, if any |
| `action` | `text` | No | — | A fixed action code (e.g., `REQUEST_CREATED`, `STAGE_APPROVED`, `ATTACHMENT_UPLOADED`) |
| `metadata` | `jsonb` | Yes | `NULL` | A snapshot of relevant fields at the time of the action |
| `created_at` | `timestamptz` | No | `now()` | Timestamp the action occurred |

- **Primary Key:** `id`
- **Foreign Keys:** `actor_id` references `profiles.id`; `request_id` references `requests.id`
- **Unique Constraints:** none
- **Indexes:** index on `request_id`; index on `actor_id`; index on `created_at`; index on `action`
- **Business Rules:** No `updated_at` column exists, and the database role used by the application is granted only `INSERT` and `SELECT` on this table — never `UPDATE` or `DELETE` — as described in Section 6.

### 3.9 Optimistic Concurrency Control

**Why concurrent updates can occur.** EAH is a multi-user system: two approvers on the same escalation queue may load the same `workflow_stages` row before either submits a decision, or an administrator editing a `profiles` row may overlap with the user's own session updating unrelated fields. Because the Application layer does not hold long-lived database locks between reading a row and writing it back (doing so would tie up connections and hurt concurrency at the stated scale), a naive read-modify-write sequence is exposed to the **lost-update problem**: the second write silently overwrites the first without either party being informed that a conflict occurred.

**Mechanism.** Every table where this risk is meaningful — `profiles`, `requests`, `workflow_stages`, and `workflow_definitions` (via its `row_version` column, distinguished from the existing business-level `version` field described in Section 3.2) — carries a monotonically increasing `version integer default 1` column. A repository update operation always:

1. Reads the row, including its current `version` value.
2. Issues the update with a `WHERE id = :id AND version = :expected_version` predicate, incrementing `version` by one as part of the same statement.
3. Inspects the number of affected rows. Zero rows affected means another writer updated the row first; the repository raises a `ConcurrentUpdateError` (surfaced by the Application layer per the ADD's error-handling strategy) rather than silently applying a stale change.

This pattern requires no additional infrastructure beyond the column itself — no distributed lock manager, no external coordination service — and stays entirely within a single PostgreSQL statement per update, consistent with the project's transactional model in Section 11.

**Why this improves consistency.** Optimistic locking converts a silent, undetectable lost update into an explicit, handleable error at the moment it actually occurs, without imposing the throughput cost of pessimistic row locking on every read. Given the expected concurrency (Section 12.1 — up to 50 concurrent users), conflicts on any single row are expected to be rare, which makes the optimistic strategy — check at write time rather than lock at read time — the appropriate trade-off.

### 3.10 Soft Deletion Strategy

Certain business entities support **soft deletion** rather than physical row removal: `requests`, `comments`, and `attachments` each carry a nullable `deleted_at` (timestamp) and `deleted_by` (referencing `profiles.id`) pair, as documented in their respective specifications above. A row with `deleted_at IS NULL` is active; a row with `deleted_at` populated is considered withdrawn or removed for application purposes, but remains physically present in the table.

**Why enterprise systems prefer soft deletion over hard deletion:**

- **Preservation of audit history.** `audit_logs` entries referencing a request, comment, or attachment must remain resolvable to a real row (per the `RESTRICT` foreign key behavior in Section 4) for the historical record to make sense. Hard-deleting the underlying business row would either violate that constraint or force `audit_logs` itself to store denormalized snapshots of data it should only be referencing. Soft deletion avoids this tension entirely: the referenced row still exists, so the audit trail remains a straightforward join rather than a reconstruction from snapshots.
- **Support for "undo" and administrative review.** A request withdrawn in error, or a comment removed by an administrator, can be reasoned about and, if the business process allows it, restored, because the data was never actually destroyed.
- **Consistency with the immutability principle already established for `audit_logs`.** Soft deletion is the natural extension of that same philosophy — "never destroy history" — applied to the handful of business tables where a user-facing notion of "removal" is still required.

Soft deletion is **not** applied uniformly across the schema. `workflow_stages`, `notifications`, `workflow_definitions`, and `audit_logs` are not soft-deletable: stages and definitions are never removed once created (only deactivated or superseded, per their own business rules), and `audit_logs` rows are never deleted in any form, soft or hard, per Section 6. Every repository method that lists rows from a soft-deletable table filters on `deleted_at IS NULL` by default, so soft-deleted rows are excluded from ordinary application views without requiring every call site to remember to add the filter explicitly.

**`profiles`** (`0020_profile_lifecycle`) has a two-tier lifecycle distinct from the pattern above, mirroring `companies`' own `is_active`/`deleted_at` split:

- `is_active` (reversible deactivation): blocks login immediately (`SupabaseTokenVerifier` checks it on every request), touches no other column, and is fully reversible.
- `deleted_at`/`deleted_by` (GDPR right-to-erasure): **irreversible**, because the same operation also overwrites `full_name`/`department` with an anonymized placeholder (`ProfileRepository.erase`) — unlike `requests`/`comments`/`attachments`/`companies`, there is no `restore` for an erased profile, since the original PII is gone. This is deliberately not physical deletion: `audit_logs.actor_id` and `requests.requester_id` are `ON DELETE RESTRICT` against `profiles.id` (Section 4), making a genuine `DELETE` of any profile with real history impossible by design — anonymization is the only path for a user who has ever done anything, which is exactly what GDPR Article 17(3) permits (retaining data in a form that no longer identifies the subject, where full erasure would conflict with legitimate audit/record-keeping needs). The corresponding Supabase Auth user's email (the one piece of PII this table doesn't hold) is scrubbed separately, via the Supabase Auth Admin API (`app.services.supabase_admin_client.SupabaseAuthAdminClient.anonymize_user`), never by deleting the `auth.users` row (see Section 4's note on `profiles.id → auth.users.id`).

`notifications` is a related but distinct case: its lifecycle is described by `is_read` plus, as of this application's notification-management UX build-out, `archived_at` (Section 8.5) — a lightweight, fully reversible "put away" timestamp, not full soft-deletion. The distinction matters: a soft-deleted row is hidden from every ordinary view by default and generally not meant to come back; an archived notification is hidden only from the recipient's own default view, remains trivially queryable (`is_archived=True`), and is restored with a single `unarchive` call. It therefore does not need `deleted_by` (no accountability question — a recipient can only archive their own notification), nor does soft-deletion's `RESTRICT`-preserving rationale apply (nothing else references a notification by foreign key).

---

## 4. Relationship Rules

Every foreign key referencing `profiles` was audited as part of the
user-deletion/GDPR-erasure feature (`0020_profile_lifecycle`) and given
one of three deliberate policies — see that migration's own docstring for
the full reasoning. In short: `RESTRICT` for core audit/business records
that must never be silently orphaned (and which, together, make a
genuine hard `DELETE` of any profile with real history impossible —
anonymization, Section 3.10, is the only path for such a user);
`CASCADE` for purely personal, ephemeral data; `SET NULL` for secondary
"who did this" attribution columns, where losing the specific link is an
acceptable trade-off.

| Relationship | Cascade / Restrict Behavior | Rationale |
|---|---|---|
| `profiles.id` → `auth.users.id` | `ON DELETE CASCADE` | If a user's identity is removed from Supabase Auth, the corresponding profile is removed with it. In practice this cascade cannot succeed for a profile with real history, since `audit_logs.actor_id`/`requests.requester_id` below are `RESTRICT` — which is why GDPR erasure anonymizes rather than deletes (Section 3.10). |
| `profiles.deleted_by` → `profiles.id` | `ON DELETE SET NULL` | If the admin who erased a profile is later erased themselves, the erased profile's own row is untouched — only the "who did this" attribution is lost. |
| `requests.requester_id` → `profiles.id` | `ON DELETE RESTRICT` | A profile cannot be deleted while it has authored requests; historical requests must always resolve to a requester. Deactivation or GDPR erasure (anonymization, never deletion), not physical deletion, is the path for offboarding a user (`profiles.is_active` / `deleted_at`). |
| `requests.deleted_by` → `profiles.id` | `ON DELETE SET NULL` | "Who soft-deleted this request" is secondary metadata; losing it is acceptable, blocking the deleter's own erasure is not. |
| `requests.workflow_definition_id` → `workflow_definitions.id` | `ON DELETE RESTRICT` | A workflow definition referenced by any existing request can never be deleted, only deactivated (`is_active = false`), preserving the historical approval chain of past requests. |
| `requests.current_stage_id` → `workflow_stages.id` | `ON DELETE SET NULL`, deferrable within the creation transaction | This is a forward reference used to answer "what stage is this request waiting on" without a join; it is nulled out automatically if the referenced stage row is ever removed, though in practice stage rows are never deleted (see below). |
| `workflow_stages.request_id` → `requests.id` | `ON DELETE CASCADE` | A stage has no independent existence outside its parent request; if a request is ever purged (an administrative action outside normal application flow), its stages are purged with it. |
| `workflow_stages.assigned_to` / `decided_by` → `profiles.id` | `ON DELETE SET NULL` | The stage's own `status`/`decided_at` remain the record of what happened; for any real decision, a corresponding `audit_logs` row (itself `RESTRICT`-protected) is the authoritative record of who acted, so losing this link on a later profile erasure doesn't lose the decision's history. |
| `workflow_definitions.created_by` → `profiles.id` | `ON DELETE SET NULL` | A workflow template outlives its author; not core audit trail. |
| `comments.request_id` → `requests.id` | `ON DELETE CASCADE` | Comments have no meaning independent of their request. |
| `comments.author_id` → `profiles.id` | `ON DELETE RESTRICT` | Preserves attribution of historical comments. |
| `comments.deleted_by` → `profiles.id` | `ON DELETE SET NULL` | Same reasoning as `requests.deleted_by`. |
| `comments.parent_comment_id` → `comments.id` | `ON DELETE CASCADE` | If a parent comment is removed (an administrative action, not a normal user action), its replies are removed with it to avoid orphaned thread fragments. |
| `attachments.request_id` → `requests.id` | `ON DELETE CASCADE` | Attachment metadata has no meaning independent of its request; the corresponding Storage object is removed by the Application layer as a coordinated step, not by a database-level trigger, consistent with the ADD's rule that repositories — not the database — own Storage interaction. |
| `attachments.uploaded_by` → `profiles.id` | `ON DELETE RESTRICT` | Preserves attribution of historical uploads. |
| `attachments.deleted_by` → `profiles.id` | `ON DELETE SET NULL` | Same reasoning as `requests.deleted_by`. |
| `notifications.recipient_id` → `profiles.id` | `ON DELETE CASCADE` | A notification has no purpose once its recipient no longer exists. |
| `notifications.request_id` → `requests.id` | `ON DELETE CASCADE` | Notifications tied to a purged request are purged with it. |
| `notification_preferences.user_id` / `saved_filters.user_id` / `search_history.user_id` → `profiles.id` | `ON DELETE CASCADE` | Purely personal, per-user settings/history with no value once their owner is gone. |
| `audit_logs.actor_id` → `profiles.id` | `ON DELETE RESTRICT` | Audit history must remain resolvable to the acting user; this is the strongest guarantee in the schema, matching the immutability principle in Section 6, and the mechanism that makes anonymization (not deletion) the only possible erasure path for any profile with audit history. |
| `audit_logs.request_id` → `requests.id` | `ON DELETE RESTRICT` | Audit entries must never be silently removed as a side effect of removing their subject request; a request is not deleted while audit history referencing it exists. |
| `user_invitations.invited_by` → `profiles.id` | `ON DELETE SET NULL` | An admin who invited many users and later left the company shouldn't block their own erasure; the invitation record itself remains meaningful without this link. |
| `user_invitations.accepted_profile_id` → `profiles.id` | `ON DELETE SET NULL` | Same reasoning. |
| `jobs.actor_id` → `profiles.id` | `ON DELETE SET NULL` | Secondary "who triggered this job" metadata; `audit_logs` is the authoritative record where one exists. |
| `companies.deleted_by` / `company_licenses.updated_by` / `feature_flags.updated_by` → `profiles.id` | `ON DELETE SET NULL` | Same "secondary attribution" reasoning as the `deleted_by` columns above. |

In practice, `requests` rows are never hard-deleted by any application code path; the `RESTRICT` behaviors above exist as a database-level safeguard against accidental deletion attempted outside the normal application flow, not as a behavior the application is expected to trigger.

### 4.1 Additional Integrity Constraints

Beyond foreign keys and enum-backed columns, a small set of `CHECK` constraints enforce business-level invariants that a column type alone cannot express. These are documentation-level recommendations, applied at the table level, that improve data integrity by rejecting impossible states at the database boundary rather than relying solely on Pydantic validation upstream:

| Table | Constraint | Rationale |
|---|---|---|
| `workflow_stages` | `stage_order > 0` | Stage ordering is 1-indexed by convention (Section 3.4); a zero or negative order has no meaning and would break the Workflow Engine's ordering logic. |
| `workflow_definitions` | `version > 0` | Version numbers are monotonically increasing business identifiers (Section 3.2); a non-positive version is meaningless and would collide with the "first version" case. |
| `attachments` | `size_bytes > 0` | A zero-byte or negative file size indicates a failed or corrupted upload; this is rejected at the database level as a final safeguard behind the Application layer's own validation. |
| `requests` | `completed_at >= created_at` (when `completed_at IS NOT NULL`) | A request cannot be recorded as completed before it was created; this guards against clock skew or application bugs producing an impossible timeline. |
| `workflow_stages` | `decided_at >= created_at` (when `decided_at IS NOT NULL`) | Mirrors the `requests` constraint above at the stage level, for the same reason. |
| `profiles`, `requests`, `workflow_stages`, `workflow_definitions` | `version > 0` / `row_version > 0` | The optimistic-locking version columns introduced in Section 3.9 must never be zero or negative, since the Repository Layer relies on straightforward integer comparison and increment. |

Each of these constraints is cheap to evaluate on write and each closes off a category of bad data that would otherwise only be caught — if at all — much later, by a report or an analytics query behaving unexpectedly.

---

## 5. Workflow Configuration Storage

### 5.1 Storage Model

Workflow definitions are stored as JSON documents in the `definition` column of `workflow_definitions`, using PostgreSQL's `jsonb` type. Each row represents one version of the approval chain for one request type. The Workflow Engine (`src/workflows`), through the Configuration Loader described in the ADD, resolves the active definition for a request type at submission time, caches it for the lifetime of the process, and uses it to determine the ordered list of stages that will be materialized as `workflow_stages` rows for that specific request.

### 5.2 Example JSON Document

```json
{
  "request_type": "expense_reimbursement",
  "version": 3,
  "stages": [
    {
      "order": 1,
      "name": "Manager Review",
      "assigned_role": "approver",
      "assignment_strategy": "requester_manager",
      "escalation_hours": 48
    },
    {
      "order": 2,
      "name": "Finance Review",
      "assigned_role": "approver",
      "assignment_strategy": "department_queue",
      "department": "finance",
      "escalation_hours": 72
    },
    {
      "order": 3,
      "name": "Final Sign-off",
      "assigned_role": "admin",
      "assignment_strategy": "specific_user",
      "assigned_user_id": "b3f1c2e4-2222-4a11-9b90-000000000001",
      "escalation_hours": 24
    }
  ]
}
```

### 5.3 Why JSON Instead of Separate Tables

The alternative to storing this configuration as JSON would be a fully normalized schema of `workflow_stage_templates`, `assignment_rules`, and related join tables. This was deliberately rejected for the following reasons:

- **The structure is read-heavy and rarely queried by its internals.** The application never needs to run a relational query such as "find all stage templates with an escalation threshold above X across every workflow type" — it only ever needs the entire ordered list of stages for one request type at a time, which a single JSON document serves far more directly than a multi-table join.
- **Versioning is simpler as a whole-document concept.** Because a definition is versioned as a single unit (Section 3.2), storing it as one JSON document means a new version is a single row insert, not a coordinated multi-table write.
- **It matches the ADD's configuration-driven philosophy.** The ADD specifies that workflow definitions are structured JSON, authored as configuration rather than code. Persisting that same JSON shape in the database (rather than only in static files) makes the source of truth queryable and auditable through ordinary PostgreSQL tooling, without introducing a second configuration format or a parallel table structure that would need to stay in lockstep with it.
- **`jsonb` still supports indexing and validation.** PostgreSQL allows a check constraint to validate top-level shape (e.g., that `stages` is a non-empty array) and supports expression indexes on JSON fields if a specific query pattern later requires one, so choosing JSON does not forfeit database-level integrity entirely.

The one thing JSON storage does **not** do is enforce referential integrity between a workflow definition's `assigned_user_id` values and `profiles.id` — this is validated by the Application layer when a definition is created or activated, not by a foreign key, since foreign keys cannot reach into a JSON document. This is a known, accepted trade-off of this design.

---

## 6. Audit Logging

### 6.1 Immutable Storage

The `audit_logs` table is designed to be **append-only** at every level of the stack:

- **Database grants.** The PostgreSQL role used by the application's Supabase connection is granted `INSERT` and `SELECT` on `audit_logs`, but not `UPDATE` or `DELETE`. This is enforced independently of whether application code ever attempts to modify a row.
- **Schema shape.** The table has no `updated_at` column, signaling structurally that a row is not expected to change after creation.
- **Repository surface.** `AuditLogRepository` (per the ADD) exposes only `insert` and read methods (`list_for_request`, `list_for_actor`); no `update` or `delete` method exists anywhere in the codebase for this table.

### 6.2 Why Audit Logs Never Update

Audit entries exist to answer, unambiguously and later, "what happened, when, and who did it." If audit rows could be edited, that guarantee would depend on trusting that no one — including a future well-intentioned maintainer — ever modified history to correct an unrelated bug or clean up a mistake. By removing the database privilege to do so, correctness of the historical record no longer depends on application-level discipline alone; it is a property of the database itself. Corrections to a misunderstanding (for example, an incorrectly logged action) are handled by inserting a new, clarifying entry, never by altering the original.

This is distinct from operational logging (Python's `logging` module, per the ADD), which is mutable in the sense that log files can be rotated or purged; `audit_logs` is a permanent business record, not an operational diagnostic tool.

---

## 7. Attachment Storage

### 7.1 Supabase Storage Integration

File content is never stored in PostgreSQL. When a user uploads a file, `AttachmentService` (per the ADD) writes the file bytes to a Supabase Storage bucket and, only after that write succeeds, inserts a corresponding row into `attachments` containing metadata and a reference path. This ordering means an `attachments` row is never created for a file that does not exist in Storage.

### 7.2 Metadata Stored in PostgreSQL

The `attachments` table (Section 3.6) stores exactly the metadata needed to locate, display, and validate a file without opening it: `file_name`, `content_type`, `size_bytes`, `storage_path`, `uploaded_by`, and `created_at`. No file content, thumbnail, or binary data is stored in PostgreSQL.

### 7.3 Storage Path Convention

Files are namespaced by request to keep the bucket organized and to prevent path collisions or traversal between unrelated requests:

```
attachments/
└── {request_id}/
    └── {attachment_id}_{sanitized_file_name}
```

- `{request_id}` scopes every file to its owning request, allowing Storage-level access rules to mirror the RLS policies applied to the `requests` and `attachments` tables.
- `{attachment_id}` guarantees uniqueness even if two files with the same original name are uploaded to the same request.
- `{sanitized_file_name}` preserves a human-readable name (with path separators and unsafe characters stripped) for display and download purposes.

---

## 8. Notification Storage

### 8.1 Table Purpose

The `notifications` table (Section 3.7) stores every notification generated for a user, whether triggered synchronously by a request-lifecycle event or asynchronously by the Scheduler (reminders, escalations), per the ADD's description of the Notification Service.

### 8.2 Unread / Read Status

Each row carries `is_read` (boolean) and `read_at` (nullable timestamp). A notification is created with `is_read = false`; the Presentation layer marks it read — setting `is_read = true` and populating `read_at` — when the user views it, via a single, idempotent update issued by `NotificationService`. There is no separate "unread notifications" table; unread notifications are simply the subset of rows where `is_read = false`, retrieved via the index described in Section 10.

### 8.3 Notification Types

The `notification_type` column constrains every row to one of a fixed set of categories, keeping the type list explicit rather than inferred from message text:

| Type | Triggered By |
|---|---|
| `assignment` | A new `workflow_stages` row is assigned to a user |
| `reminder` | The Scheduler's Reminder Dispatch job, for stages still pending |
| `escalation` | The Scheduler's Escalation Check job, for stages past their threshold |
| `decision` | A stage is approved or rejected, notifying the requester |
| `completion` | A request reaches a terminal status |
| `system` | Administrative or configuration-level events (e.g., a workflow definition was activated) |

### 8.4 Email Mirroring

Per the ADD, every notification is also dispatched as an email as part of the baseline. `email_sent` and `email_sent_at` record the outcome of that dispatch independently of the row's existence — a failed email send does not remove or invalidate the in-app notification, and a retry mechanism (implemented at the Application layer, not the database layer) may update `email_sent` from `false` to `true` after a successful later attempt.

### 8.5 Archive Status

`archived_at` (nullable timestamp) lets a recipient remove a notification from their default, active view without deleting it or losing its `is_read`/`read_at` history. `NotificationRepository.list_for_recipient`'s `is_archived` parameter defaults to `False` (the active view, `archived_at IS NULL`); a caller may instead request `True` (only archived notifications) or `None` (both). Archiving is fully reversible via a single `unarchive` call, and an archived notification never contributes to `get_unread_count` — archiving is how a recipient signals a notification no longer needs their attention, independent of whether they had already read it. See Section 3.10 for how this differs from this schema's soft-deletion strategy.

---

## 9. Row Level Security

### 9.1 Strategy

RLS is enabled on every table described in Section 3 except `workflow_definitions`, which is administrator-managed and readable by all authenticated users (since any user must be able to resolve the active definition for a request type they are submitting). RLS policies are the authoritative enforcement layer for data access — they hold even if an Application-layer permission check is ever missed or contains a bug, consistent with the defense-in-depth principle in the ADD.

Policies are expressed here at the level of intent; they are implemented as PostgreSQL policies referencing the authenticated user's id (`auth.uid()`) and their `profiles.role`, resolved via a lookup against the `profiles` table.

### 9.2 Policies by Role

**Submitter (the requester)**

| Table | Access |
|---|---|
| `requests` | May `SELECT` and `INSERT` rows where `requester_id = auth.uid()`. May not `UPDATE` status directly; status changes flow only through the Application layer under a role that has update privilege, not through direct client writes. |
| `workflow_stages` | May `SELECT` stages belonging to their own requests; may not `INSERT` or `UPDATE`. |
| `comments` | May `SELECT` and `INSERT` comments on their own requests; may not modify or delete existing comments. |
| `attachments` | May `SELECT` and `INSERT` attachments on their own requests. |
| `notifications` | May `SELECT` and `UPDATE` (read-status only) rows where `recipient_id = auth.uid()`. |
| `audit_logs` | May `SELECT` entries where `request_id` belongs to one of their own requests. |

**Approver**

| Table | Access |
|---|---|
| `requests` | May `SELECT` requests where they are the requester, or where they are `assigned_to` on a `workflow_stages` row belonging to that request. |
| `workflow_stages` | May `SELECT` stages where `assigned_to = auth.uid()` or `assigned_role` matches their `profiles.role`; may `UPDATE` (decision fields only) a stage where they are the resolved assignee and `status = 'pending'`. |
| `comments` | May `SELECT` and `INSERT` comments on requests they are assigned to review. |
| `attachments` | May `SELECT` attachments on requests they are assigned to review. |
| `notifications` | Same as Submitter, scoped to their own `recipient_id`. |
| `audit_logs` | May `SELECT` entries for requests they are or were assigned to review. |

**Administrator**

| Table | Access |
|---|---|
| `requests` | May `SELECT` all rows across the organization. Direct `UPDATE`/`DELETE` outside the Application layer's own write path is not granted even to administrators, preserving a single, auditable code path for state transitions. |
| `workflow_stages` | May `SELECT` all rows; may `INSERT`/`UPDATE` in the limited case of manual escalation reassignment, performed through the Application layer. |
| `workflow_definitions` | May `INSERT` and `UPDATE` (`is_active` flag and new versions); may not `DELETE` existing versions, consistent with the `ON DELETE RESTRICT` behavior in Section 4. |
| `comments`, `attachments` | May `SELECT` all rows for oversight and support purposes; may not delete or alter user-authored content. |
| `notifications` | May `SELECT` all rows for support/debugging; may not alter another user's read status. |
| `audit_logs` | May `SELECT` all rows. No role, including `admin`, is granted `UPDATE` or `DELETE` on this table, per Section 6. |

### 9.3 Service-Role Credentials and Defense-in-Depth

Supabase issues two distinct kinds of API keys: an **anon** key, used by client-authenticated requests and always subject to RLS, and a **service-role** key, which connects with elevated privileges and bypasses RLS entirely. EAH's Application layer and Scheduler (per the ADD) use the service-role credential exclusively on the server side — inside the Python process running Streamlit and APScheduler — and never expose it to the browser or any client-side code.

**Why backend services may bypass RLS.** The Application layer is itself the enforcement point for authorization decisions that RLS cannot express as a simple row-ownership predicate — for example, the Workflow Engine resolving the next assignee for a stage, or the Scheduler's Escalation Check evaluating pending stages across every request in the system regardless of who is "assigned" to them. These operations are legitimately cross-cutting and are already gated by the Application layer's own role and permission checks (Section 8 of the ADD) before any database call is made, so re-deriving the same authorization through RLS predicates would be redundant rather than protective.

**Why client operations remain protected by RLS.** Anything reachable from the browser — any Streamlit session acting on a user's behalf — connects using the anon key and is therefore always subject to the RLS policies in Section 9.2, regardless of what the Presentation layer's own code does or fails to check. This is the same defense-in-depth principle described in the ADD's Security Architecture: application-level authorization checks and database-level RLS are two independent layers, and a bug in one does not remove the protection of the other. The service-role key's elevated access is deliberately confined to trusted, server-side code paths that have already passed through the Application layer's own authorization logic — it is never a substitute for RLS on the client-facing surface, only a necessary capability for the small set of legitimately cross-cutting backend operations described above.

### 9.4 `companies` Table and `FORCE ROW LEVEL SECURITY`

`companies` (added by the multi-tenancy conversion, migrations `0009`-`0011`) carries RLS too: an authenticated user may `SELECT` only their own company's row (`id = current_profile_company()`); no `INSERT`/`UPDATE`/`DELETE` grant is given to `authenticated` at all, since company creation and management is exclusively a service-role, platform-admin-gated operation (`CompanyService`) — client code never modifies this table directly.

Every table in this section additionally has `FORCE ROW LEVEL SECURITY` set (migration `0014`). This has no effect on the service-role client — its `BYPASSRLS` role attribute always wins regardless of `FORCE` — but closes a narrower, latent gap: a connection authenticated as a table's owner (a direct `psql` session, a migration role, or an admin tool) bypasses RLS by default even without `BYPASSRLS`, unless `FORCE` is set.

---

## 10. Database Indexing Strategy

### 10.1 Single-Column Indexes

| Table | Index | Purpose |
|---|---|---|
| `requests` | `status` | Supports filtered lists such as "all pending requests" and dashboard counts by status. |
| `requests` | `request_type` | Supports filtering and analytics grouped by request type, and resolving the active workflow definition. |
| `requests` | `created_at` | Supports chronological listing and date-range analytics queries. |
| `requests` | `department` | Supports department-scoped views for managers and department-level analytics. |
| `requests` | `requester_id` | Supports "my requests" lookups for the submitter view. |
| `workflow_stages` | `request_id` | Supports retrieving all stages for a given request (the most common access pattern for this table). |
| `workflow_stages` | `status` | Supports finding all pending stages system-wide, used by the Scheduler's Escalation Check and Reminder Dispatch jobs. |
| `workflow_stages` | `assigned_to` | Supports "my pending approvals" lookups for the approver view. |
| `comments` | `request_id` | Supports retrieving the full comment thread for a request. |
| `comments` | `parent_comment_id` | Supports resolving reply threads efficiently. |
| `attachments` | `request_id` | Supports retrieving all attachments for a request. |
| `notifications` | `recipient_id` | Supports retrieving a user's notification list. |
| `notifications` | `is_read` | Supports efficiently counting and listing unread notifications, the most frequent notification query. |
| `notifications` | `request_id` | Supports correlating notifications back to their source request for audit/debugging. |
| `notifications` | `created_at` | Supports chronological ordering of a user's notification feed. |
| `audit_logs` | `request_id` | Supports retrieving the full audit trail for a specific request. |
| `audit_logs` | `actor_id` | Supports retrieving a user's action history. |
| `audit_logs` | `created_at` | Supports chronological and date-range audit queries. |
| `audit_logs` | `action` | Supports filtering the audit trail by action type for reporting. |
| `profiles` | `role` | Supports resolving all users with a given role, used when assigning role-based stages. |
| `profiles` | `department` | Supports department-scoped user lookups. |
| `workflow_definitions` | `request_type` | Supports resolving definitions by type. |
| `workflow_definitions` | `is_active` (partial) | Supports the frequent "find the active definition for this type" lookup with a minimal index footprint. |

Every index above corresponds to a query pattern already named explicitly in the ADD's Request Lifecycle (Section 5 of that document) or Component Breakdown — no index is added speculatively for a query the application does not perform.

### 10.2 Composite Indexes for Common Query Patterns

The single-column indexes above are sufficient for filtering on one predicate at a time, but several of the application's most frequent queries filter on **two** columns together. A composite index ordered to match the query's filter pattern serves these lookups directly, rather than requiring PostgreSQL to intersect two separate single-column indexes at query time:

| Table | Composite Index | Query Pattern Supported |
|---|---|---|
| `requests` | (`requester_id`, `status`) | "My requests filtered by status" — the submitter's default view, filtering to a specific status such as `pending` within their own requests. |
| `requests` | (`status`, `created_at`) | "All requests in a given status, ordered by age" — used by dashboard and escalation-adjacent views that need the oldest pending requests first. |
| `workflow_stages` | (`assigned_to`, `status`) | "My pending approvals" — the approver's default view, filtering a specific user's assigned stages down to `status = 'pending'`. |
| `notifications` | (`recipient_id`, `is_read`) | "My unread notifications" — the single most frequent notification query, run on every page load to populate a notification badge. |
| `notifications` | (`recipient_id`, `archived_at`) | "My active notifications" (the default Notification Center view) and "my archived notifications," both filtered on this pair. |
| `requests` | (`company_id`, `status`) | The Analytics Layer's `count_requests_by_status` — every dashboard/workflow/department metric's status breakdown, always filtered to the caller's own company, and (since migration `0022`) grouped by this same pair inside Postgres itself. |
| `requests` | (`company_id`, `created_at` desc) | The Analytics Layer's date-range aggregates (`count_requests_by_type`, `count_requests_by_department`, `approval_throughput`, `get_request_trend`), all scoped to one company and ordered/filtered by submission date. |
| `requests` | (`company_id`, `request_type`) | The Analytics Layer's `count_requests_by_type` — `request_type` is this query's `group by` column, not just an optional filter, once it runs as a real SQL aggregate (migration `0021`). |
| `requests` | (`company_id`, `department`) | The Analytics Layer's `count_requests_by_department` — same reasoning, for `department` as the `group by` column (migration `0021`). |
| `workflow_stages` | (`company_id`, `status`) | The approver's pending-approvals queue (`list_pending_for_approver`) and the Analytics Layer's company-scoped workload summary (`list_overdue_stages` called with an explicit `company_id`), both requiring a same-company, same-status match — the multi-tenancy conversion's `company_id` column on this table exists specifically because no `request_id` is in hand to scope through otherwise. |
| `audit_logs` | (`company_id`, `created_at` desc) | The organization-wide "Recent Activity" feed and admin dashboard's recent-activity panel (`AuditRepository.list_all`, always company-scoped), and the Analytics Layer's escalation count — all read newest-first within one company. |
| `audit_logs` | (`company_id`, `action`, `created_at` desc) | `OperationalAnalyticsEngine`'s approval/rejection-trend bucketing and workload-summary activity counts, which filter `list_all` on `action` in addition to `company_id` (migration `0013`). |
| `profiles` | (`company_id`, `role`, `department`) | `ProfileRepository.list_by_role` — the `department_queue` assignment strategy's eligible-approver resolution and the admin user directory, both filtering role and (optionally) department within one company (migration `0023`). |
| `requests` | (`company_id`, `requester_id`) | An `employee`-role caller's "my requests" view (`RequestService.list_requests`) — the single most frequently issued list query in the application (migration `0024`). |
| `audit_logs` | (`company_id`, `actor_id`, `created_at` desc) | `GET /api/v1/activity`, the caller's own activity feed — issued by every authenticated user, newest first (migration `0024`). |
| `user_invitations` | (`company_id`, `status`, `expires_at`) | `InvitationRepository.list_invitations`'s admin invitation-management view, replacing a pre-multi-tenancy `(status, expires_at)` index that had no `company_id` leading column (migration `0024`). |

These composite indexes do not replace the single-column indexes in Section 10.1: some queries (e.g., "all requests in a department," or `AuditRepository.list_for_actor`'s "all audit entries by one actor, regardless of company") still filter on only one of these columns, and the single-column indexes remain the more efficient path for those cases. The two sets of indexes are complementary, chosen to match the two distinct shapes of query the application actually issues.

Deliberately not added: a `workflow_definitions (company_id, request_type)` composite for the general definition-listing/search path. That table holds a handful of rows per company (one row per request-type version, not one per business transaction), the access pattern is a rare admin operation, and its highest-value case — finding *the* active definition for a type — is already served by the existing partial unique index, `workflow_definitions_active_uidx (company_id, request_type) where is_active`. Adding a further index here would be speculative rather than justified by query frequency or table growth, unlike every index in the table above.

Every `AnalyticsRepository` aggregate (`count_requests_by_status`/`_by_type`/`_by_department`/`approval_throughput`) is computed inside Postgres via a `group by`/`count`/`avg`, not by fetching every matching row and grouping in Python — see `app/database/migrations/versions/0022_analytics_aggregation_functions.py`. Each function returns only the aggregated rows (at most one per status/type/department, or a single row for throughput), rather than one row per matching request or workflow stage.

### 10.3 Substring Search Is Deliberately Unindexed

The global-search feature's per-entity substring queries (`comments.body`, `audit_logs.action`, `profiles.full_name`, `workflow_definitions.request_type`, alongside the pre-existing `requests.title`/`requests.description`) all use a plain, unindexed `ILIKE '%term%'` predicate. A leading `%` wildcard cannot use a standard B-tree index regardless of whether one exists, so no index is added for these columns purely to support search — doing so would be a genuine no-op, not a missed optimization. Real index-accelerated substring/typo-tolerant search would require PostgreSQL's `pg_trgm` extension and a GIN trigram index per searched column, which this schema does not provision (see the Global Search endpoint's own "Matching" note, API-ADD Section 19.11.1, for the resulting, deliberate scope this implies). At this application's documented scale (SRS Section 12.1), a sequential scan per search term is the accepted trade-off; `pg_trgm` is the natural first upgrade if search volume or table size ever makes that unacceptable.

---

## 11. Transactions

The following operations must be executed within a single database transaction, issued from the Repository Layer, because they leave more than one row (or more than one table) in a related, interdependent state:

| Operation | Statements Involved | Why a Transaction Is Required |
|---|---|---|
| **Request creation** | Insert into `requests`; insert the first `workflow_stages` row; update `requests.current_stage_id` to point to it; insert an `audit_logs` entry | A request must never exist without an initial stage, and a stage must never exist without belonging to a fully-formed request; both rows (and the back-reference) must commit together or not at all. |
| **Approval decision** | Update the current `workflow_stages` row (`status`, `decided_by`, `decided_at`); insert the next `workflow_stages` row if further stages remain, or update `requests.status`/`completed_at` if not; update `requests.current_stage_id`; insert an `audit_logs` entry | A decision and the resulting state change (next stage or completion) must be atomic — a reader must never observe a stage marked `approved` while the request still points to it as the current stage, or a completed request with no corresponding final stage update. |
| **Comment creation** | Insert into `comments`; insert an `audit_logs` entry | Ensures every comment is recorded in the audit trail as an atomic pair; a comment should never exist without its corresponding audit entry, given the audit table's role as the authoritative activity record. |
| **Attachment upload** | Write to Supabase Storage (outside PostgreSQL); insert into `attachments`; insert an `audit_logs` entry | The `attachments` insert and the `audit_logs` insert are wrapped in a single PostgreSQL transaction, issued only after the Storage write has already succeeded. This ordering (Storage first, then a single database transaction) avoids ever recording metadata for a file that does not exist, while still keeping the two database rows consistent with each other. |
| **Workflow definition activation** | Update the previously active row's `is_active` to `false`; insert the new version with `is_active = true` | Prevents a window in which two versions of the same `request_type` are simultaneously marked active, which would make the Workflow Engine's "resolve the active definition" query ambiguous. |

Read-only operations (listing requests, retrieving a comment thread, fetching notifications) are not transactional beyond PostgreSQL's default read-committed isolation, since they do not modify state.

---

## 12. Performance Considerations

### 12.1 Expected Scale

The schema is designed against the SRS's stated scale target: approximately 100,000+ cumulative requests and up to 50 concurrent users. At this scale, EAH operates well within the comfortable range of a single, properly indexed PostgreSQL instance on Supabase's managed infrastructure; no partitioning, sharding, or read-replica requirement is anticipated at this volume, though the option remains available (see Section 14).

### 12.2 Indexing Strategy at Scale

The indexes listed in Section 10 are chosen specifically to keep the most frequent queries — "my pending approvals," "requests by status," "unread notifications," "audit trail for a request" — index-backed rather than requiring a sequential scan, even as the `requests`, `workflow_stages`, `notifications`, and `audit_logs` tables grow into the hundreds of thousands of rows. Because `audit_logs` and `notifications` are append-only or append-heavy and grow fastest, their indexes are deliberately narrow (single-column, or a partial index for `workflow_definitions.is_active`) to keep write overhead low relative to the read benefit.

### 12.3 Query Shape

Nearly all high-frequency queries described in the ADD's Request Lifecycle are single-table, index-backed lookups filtered by a foreign key or status column (e.g., "stages where `assigned_to = X` and `status = 'pending'`"), rather than wide multi-table joins across the full dataset. The one place a document-style read replaces a join — resolving a workflow definition — is precisely the `jsonb` column discussed in Section 5, which avoids what would otherwise be a multi-table join for a value that is read as a whole document, not filtered by its internal fields.

### 12.4 Connection Usage

At 50 concurrent users, connection volume from the Streamlit application (and its in-process APScheduler jobs) remains well within Supabase's managed connection pooling limits for its standard tiers; no additional connection-pooling infrastructure beyond what Supabase provides is introduced.

### 12.5 PostgreSQL Maintenance

Supabase's managed PostgreSQL instance runs **autovacuum** by default, which reclaims space left behind by updated or soft-deleted rows (Section 3.10) and updated `version` columns (Section 3.9), and periodically runs **ANALYZE** to keep the query planner's statistics current as table sizes grow. At the scale described in Section 12.1 (100,000+ requests, 50 concurrent users), the default autovacuum thresholds are expected to keep pace with the write volume this schema produces without manual tuning. No manual `VACUUM`, `ANALYZE`, or custom maintenance job is planned for the baseline system; this is revisited only if query performance monitoring (available through Supabase's dashboard) indicates planner statistics have gone stale faster than autovacuum's default schedule accounts for, which is not expected at the projected workload.

---

## 13. Backup and Recovery

### 13.1 Supabase-Managed Backups

EAH relies entirely on Supabase's built-in backup infrastructure rather than any custom backup tooling, consistent with the project's constraint of introducing no infrastructure outside the fixed stack. Supabase provides automated daily backups of the PostgreSQL database as part of its managed offering, retained according to the project's subscription tier.

### 13.2 Point-in-Time Recovery

On tiers that support it, Supabase's point-in-time recovery (PITR) capability allows the database to be restored to a specific moment within the retention window, which is the intended recovery mechanism for scenarios such as an erroneous bulk update or an accidental deactivation of a workflow definition. EAH's schema does not require any special preparation to benefit from PITR — because every state-changing write is already transactional (Section 11), a PITR restore always returns the database to a point where every table is in a mutually consistent state, never a "half-committed" one.

### 13.3 Disaster Recovery Assumptions

The disaster recovery posture for EAH assumes Supabase's own infrastructure-level redundancy (managed by Supabase, not by EAH) for the underlying PostgreSQL instance and Storage buckets. EAH does not implement its own replication, failover, or cross-region redundancy; doing so would introduce infrastructure explicitly outside the fixed stack. Recovery time and recovery point objectives for EAH are therefore bounded by Supabase's own published guarantees for the project's subscription tier, and this document assumes those guarantees are adequate for the scale and criticality described in the SRS.

---

## 14. Future Database Evolution

The schema is intentionally shaped so that several plausible future requirements can be absorbed as additive changes rather than a redesign:

**Slack and Teams integration.** Both would consume the existing `notifications` table as their data source: a new `notification_type` value (or a new delivery-channel column analogous to `email_sent`/`email_sent_at`, e.g., `slack_sent`/`teams_sent`) would let the same `NotificationService` dispatch to an additional channel without altering `requests`, `workflow_stages`, or any other table. No new foreign keys or relationships are required.

**Additional workflow types.** Because approval chains are data (Section 5), a new request type is a new `workflow_definitions` row, not a schema change. The `requests.request_type` and `workflow_stages` structure already generalize to any number of types without modification.

**Multi-tenancy (future).** If EAH were extended to serve multiple organizations, the schema is positioned to absorb this by introducing a single `tenant_id` column on `profiles`, `requests`, `workflow_definitions`, `notifications`, and `audit_logs`, paired with an extension of the existing RLS policies (Section 9) to additionally filter by `tenant_id`. Because RLS is already the authoritative enforcement mechanism in this design, adding a tenant dimension is a matter of extending existing policies with one more predicate, not introducing a new enforcement architecture. No table needs to be split, merged, or re-keyed to accommodate this.

**Growth beyond current scale.** Should request volume grow well beyond the SRS's stated target, the append-heavy tables (`audit_logs`, `notifications`) are the natural first candidates for native PostgreSQL table partitioning by `created_at` — a schema-compatible change that requires no application code changes, since partitioning is transparent to the Repository Layer's queries.

None of these evolutions require introducing technology outside PostgreSQL, Supabase, or the application's existing Python stack, and none require altering the responsibilities assigned to the layers described in the Architecture Design Document.

---

## 15. Migration Strategy

Schema changes are managed through **Alembic**, used strictly as a development-time and deployment-time tool for version-controlling and applying schema changes against the Supabase PostgreSQL instance — it introduces no runtime dependency into the application itself and has no presence in `src/`, consistent with the ADD's fixed technology stack.

**Version-controlled migrations.** Every schema change — a new table, a new column, a new enum type or value, a new constraint — is captured as an Alembic migration script, checked into the same repository as the application code. The migration history is the single source of truth for how the schema arrived at its current shape; it is never inferred from comparing environments after the fact.

**Forward-only migration philosophy.** Migrations are written to move the schema forward, one deliberate step at a time. Rather than editing or deleting a previously applied migration to "fix" it, a correction is expressed as a new migration, mirroring the same append-only philosophy already applied to `audit_logs` (Section 6): the migration history itself becomes an accurate record of how the schema actually evolved, mistakes included, rather than a rewritten idealization of it.

**Testing migrations before production deployment.** Each migration is applied and verified against a disposable local or staging PostgreSQL instance before being applied to the production Supabase project, exercising both the upgrade path and, for any migration that supports it, the corresponding downgrade path. This is treated as a standard step in the deployment process for EAH, not an optional one, given that a failed or partial migration against production data is far costlier to recover from than a caught failure in staging.

Alembic operates independently of Supabase's own SQL-based migration tooling; either can express the same underlying schema changes, and this document assumes Alembic as the primary mechanism because it keeps schema versioning in the same Python-native toolchain as the rest of the application's development workflow.

---

## 16. Database Naming Conventions

The schema follows a single, consistent naming convention throughout, so that any table or column's purpose and shape can be inferred from its name alone without consulting this document:

| Convention | Example | Applies To |
|---|---|---|
| `snake_case` table names | `workflow_stages`, `audit_logs` | All tables |
| `snake_case` column names | `requester_id`, `created_at` | All columns |
| Plural table names | `requests`, `comments`, `notifications` | All tables (a table holds a collection of rows of that entity) |
| `uuid` primary keys, always named `id` | `requests.id`, `comments.id` | Every table |
| Foreign key columns end with `_id` | `request_id`, `requester_id`, `assigned_to`\* | All foreign key columns |
| Timestamp columns end with `_at` | `created_at`, `decided_at`, `deleted_at` | All `timestamptz` columns |
| Boolean columns begin with `is_` or `has_` | `is_active`, `is_read` | All boolean columns |

\* `assigned_to` and `decided_by` are the two deliberate exceptions to the `_id` suffix convention: both already read naturally as a reference to a person performing a role (an assignee, a decider) without the suffix, and both are documented explicitly as foreign keys in their table's specification regardless of naming, so the exception does not create ambiguity in practice.

This convention is applied retroactively to every table already described in Section 3 and is expected to govern any table added under the evolution paths described in Section 14.