# Enterprise Automation Hub (EAH)
## API Design Document (ADD-API)

**Version:** 2.0
**Status:** Finalized — consistent with the SRS, Architecture Design Document (ADD), and Database Schema Design Document (DSD)
**Author:** Principal Software Architect
**Base Path:** `/api/v1`

> **Superseded note:** This document originally specified a *conceptual*
> REST contract sitting on top of direct in-process calls from a Streamlit
> Presentation Layer — at the time, `/api/v1` was not a real HTTP server.
> It now **is**: `app/api/` is a live FastAPI application implementing this
> base path, and the Presentation Layer is a separate Next.js 15 / React 19
> frontend (`frontend/`) that consumes it over real HTTP, not in-process
> Python calls. The resource/verb/status-code contract described below is
> the one actually implemented; only its framing as calls "Streamlit makes
> in-process" is historical. See `docs/deployment.md` for the current
> architecture.

---

## Table of Contents

1. Overview
2. API Design Principles
3. API Conventions
4. Enumerations
5. Authentication
6. Authorization
7. API Versioning
8. Request Standards
9. Response Standards
10. Resource Schemas
11. Error Handling
12. Pagination
13. Filtering and Sorting
14. Idempotency
15. Rate Limiting
16. Deprecation Policy
17. Request Lifecycle Diagram
18. Endpoint Summary Table
19. Endpoint Specifications
20. State Transition Tables
21. Endpoint Transaction Guarantees
22. Validation Rules
23. File Upload Handling
24. Security Considerations
25. Performance Considerations and Expectations
26. Non-Functional Guarantees
27. Observability
28. API Documentation Strategy
29. API Testing Strategy
30. Sequence Diagrams
31. Example End-to-End Workflow
32. Future Evolution
33. Glossary

---

## 1. Overview

### 1.1 Purpose

This document formally specifies the request/response contract through which the Presentation Layer (Streamlit, per the ADD) invokes the Application Layer (`src/services`). It exists so that every operation the system performs — creating a request, deciding an approval, uploading a file, reading a notification — has one precise, versioned, testable definition, independent of whichever specific UI widget happens to trigger it.

### 1.2 Architectural Role

The ADD describes a strict layering: Presentation → Application Services → Domain → Repository → Database, with Streamlit calling Application Service methods as direct, in-process Python function calls. This document does not change that. What it adds is a **formal interface contract**, expressed in REST semantics (resources, HTTP verbs, status codes, JSON payloads), that sits directly on top of the same Application Service methods already described in the ADD.

Concretely: today, a Streamlit callback that submits a request invokes `RequestService.submit_request(...)` directly, in the same process, exactly as the ADD's Request Lifecycle describes. This document specifies that same operation as `POST /api/v1/requests` — same validation, same transaction boundary, same audit entry, same service method underneath. The REST specification is the contract; the current physical binding is an in-process call that satisfies it. This is a deliberate choice, not an oversight:

- It gives every operation in the system a single, unambiguous, industry-standard specification that a reviewer, a new engineer, or an automated test suite can read without first understanding Streamlit's internal callback wiring.
- It costs nothing today — no HTTP server, no new framework, no network hop is introduced, and the fixed technology stack (Python 3.11, Streamlit, Supabase, Pydantic v2, APScheduler, Plotly, pytest) is unchanged.
- It positions the system for the future evolution the ADD already anticipates without requiring the Application Layer to be redesigned when an actual network entry point is built — Section 32 returns to this.

### 1.3 REST Philosophy

The API is resource-oriented: nouns (`requests`, `comments`, `attachments`, `notifications`) rather than verbs, with HTTP methods carrying the action. This mirrors the domain model already fixed by the DSD — each resource in this specification corresponds one-to-one with a table described there and one-to-one with an Application Service described in the ADD.

### 1.4 Relationship with the Modular Monolith

Nothing in this specification implies decomposition into services. Every endpoint below is served by the same single Python process, the same Application Services, and the same Repository Layer already defined. The specification is a contract layer, not a deployment topology.

### 1.5 Why REST Was Selected

- **Resource alignment.** EAH's domain is already a set of well-defined entities with clear ownership and lifecycle. REST's resource model maps onto this directly, with no impedance mismatch to resolve.
- **Familiarity and reviewability.** A REST contract is immediately legible to any engineer without EAH-specific context — an important property for a portfolio project meant to be read by reviewers and future maintainers.
- **Compatibility with the fixed stack.** REST requires nothing beyond JSON serialization (already provided by Pydantic v2) and presupposes no particular server framework, keeping this specification implementable exactly as described in Section 1.2.

---

## 2. API Design Principles

**Resource-oriented design.** URIs identify resources (`/requests/{id}`), never actions. Actions that do not map cleanly onto CRUD (approving a stage, activating a workflow version) are modeled as sub-resource actions (`/workflow-stages/{id}/approve`) rather than invented HTTP verbs.

**Stateless communication.** Every request carries everything needed to authorize and process it — principally the bearer token described in Section 5 — and the Application Layer holds no per-request session state between calls.

**Predictable URIs.** Resource paths are always plural nouns, nested only one level deep to reflect true ownership, and identifiers are always UUIDs.

**Idempotency.** Discussed in full in Section 14, given its importance to the Approval and Workflow Definition endpoints.

**Consistency.** Every list endpoint paginates the same way (Section 12), every error looks the same shape (Section 11), every timestamp uses the same format (Section 8), and every resource identifier is a UUID (Section 3).

**Backwards compatibility.** A field is never removed or repurposed within a version; only additive, optional changes are made to `v1`.

**Versioning philosophy.** The API is versioned in the URI (`/api/v1/...`), not in a header or query parameter, because a URI-visible version is unambiguous in logs, in browser network tabs, and in this document itself.

**JSON as the exchange format.** Every request and response body is JSON, UTF-8 encoded, matching Pydantic v2's native serialization.

---

## 3. API Conventions

This section fixes the low-level notational rules that every endpoint in Section 19 follows without restating them individually.

### 3.1 Naming Conventions

- **Resource collections** are plural, `snake_case`-free, lower-kebab-case in the URI (`/workflow-stages`, `/workflow-definitions`), matching the plural `snake_case` table names in the DSD conceptually while using URL-appropriate hyphenation.
- **JSON field names** are `snake_case`, matching the underlying Pydantic model field names and PostgreSQL column names exactly (`request_type`, `created_at`, `assigned_to`) — there is no camelCase translation layer, so a field name is identical whether read in this document, in the DSD, or in a debugger.

### 3.2 Boolean Naming

Boolean fields are always prefixed `is_` or `has_` (`is_active`, `is_read`), per the DSD's own naming convention (DSD Section 16). A boolean is never named as a bare adjective or noun (never `active`, never `read`) so that its type is inferable from its name alone.

### 3.3 Enum Conventions

Enum-valued fields are always lowercase `snake_case` strings on the wire (`"in_review"`, not `"IN_REVIEW"` or `2`), matching the native PostgreSQL enum values defined in the DSD exactly. Every enum used anywhere in this API is defined once, centrally, in Section 4 — no endpoint specification in Section 19 repeats an enum's value list inline.

### 3.4 Null Handling

A field's value is `null` only when the underlying column is nullable in the DSD (e.g., `requests.description`, `workflow_stages.decided_at`). A field is never `null` to mean "not applicable" versus `false`/`0`/`""` to mean something else — nullability always mirrors the database's own nullability, keeping this API's null semantics a direct reflection of DSD Section 3, not an independently invented convention.

### 3.5 Field Omission Policy

Response bodies always include every documented field for a resource, even when its value is `null` — fields are never omitted based on their value. This keeps client-side deserialization predictable: a client can always assume a documented field key is present, and only needs to check whether its value is `null`. Request bodies (`POST`/`PATCH`) follow the opposite rule: only fields the caller intends to set are included, per Section 3.6.

### 3.6 PATCH Semantics

`PATCH` request bodies are **partial merge patches**, not full-resource replacements: only fields present in the payload are considered for update. A field's absence from a `PATCH` body means "leave unchanged," not "clear this field." To explicitly clear a nullable field, the caller sets it to `null` — an intentional value — rather than omitting it. Fields that are never client-mutable (e.g., `requests.status`, `id`, `created_at`) are rejected with `422` if present in a `PATCH` body (Section 22), rather than silently ignored.

### 3.7 Collection Naming

Every collection endpoint uses the plural form of its resource (`/comments`, `/attachments`, `/notifications`); a single resource is retrieved by appending its UUID (`/comments/{id}`). There is no singular-form alias for any collection.

### 3.8 UUID Format

Every identifier is a UUID v4, rendered in canonical lowercase, hyphenated form (`3f1a9c2e-1111-4a11-9b90-000000000010`), matching PostgreSQL's default `uuid` text representation exactly — no compact/base64 identifier encoding is used anywhere in this API.

### 3.9 Pagination Defaults

`page` defaults to `1`; `page_size` defaults to `20` and is capped at `100`. These defaults are fixed values, not per-endpoint overrides, so that the same client-side pagination component works identically against every list endpoint in Section 19. Full detail in Section 12.

### 3.10 Sorting Syntax

The `sort` query parameter takes a field name, optionally prefixed with `-` for descending order (`?sort=-created_at`). Only one sort field is supported per request in this baseline (no compound multi-field sort), which is sufficient for every list view described in the ADD's Component Breakdown and keeps the corresponding query index-backed per DSD Section 10. Each endpoint's specification in Section 19 states its default sort and its allowed `sort` values.

---

## 4. Enumerations

Every enum-valued field used anywhere in this API is defined once, here, and referenced by name elsewhere. This mirrors the DSD's own centralization of enum types (DSD Section 1.5) — the values below are identical to the native PostgreSQL enum values, not a separate API-level vocabulary.

| Enum | Values | Used By |
|---|---|---|
| `user_role` | `employee`, `approver`, `admin` | `profiles.role` |
| `request_status` | `pending`, `in_review`, `approved`, `rejected`, `completed` | `requests.status` |
| `stage_status` | `pending`, `approved`, `rejected`, `skipped` | `workflow_stages.status` |
| `notification_type` | `assignment`, `reminder`, `escalation`, `decision`, `completion`, `system` | `notifications.notification_type` |

Adding a new enum value is an additive, non-breaking change within `v1` (Section 7.2) only if existing clients are already expected to tolerate an unrecognized value gracefully (e.g., displaying it verbatim); otherwise it is treated as a breaking change requiring a version bump, consistent with Section 7.

---

## 5. Authentication

### 5.1 Provider

All authentication is delegated to Supabase Auth (GoTrue), exactly as described in the ADD and DSD. This API does not implement its own login form processing, password storage, or token issuance; it validates tokens that Supabase has already issued.

### 5.2 JWT Bearer Tokens

Every authenticated request carries an `Authorization` header:

```
Authorization: Bearer <supabase-issued-jwt>
```

### 5.3 Authenticated Requests

`AuthService`, on receiving a request, validates the JWT's signature and expiry against Supabase's published verification key, then resolves the corresponding `profiles` row to obtain `role` and `department` for authorization purposes (Section 6). A request with a missing, malformed, or expired token never reaches an Application Service method; it is rejected with `401 Unauthorized` before any business logic executes.

### 5.4 Authorization Flow

1. The user authenticates through Supabase Auth (outside this API's surface).
2. Supabase issues a JWT and refresh token to the client.
3. Every subsequent call attaches the JWT as a bearer token.
4. `AuthService` validates the token and resolves `profiles.role` for the RBAC check (Section 6).
5. On expiry, the client silently refreshes the session via Supabase's own client library.

### 5.5 Token Validation

Token validation is signature- and expiry-based only; this API does not maintain its own session store or token blacklist.

### 5.6 Session Handling

Session state lives in Streamlit's session state for the duration of the browser session, per the ADD — this API does not require or expose a server-side session mechanism.

---

## 6. Authorization

### 6.1 RBAC Model

Authorization uses the three-role model fixed by the DSD's `user_role` enum (Section 4): `employee`, `approver`, `admin`.

### 6.2 Permissions by Role

**Employee (Submitter)** — May create requests, view and search their own requests, comment on and attach files to their own requests, view their own notifications, and view the audit trail of their own requests. May not view other users' requests, decide any approval stage, or manage workflow definitions.

**Approver** — Has every Employee permission for their own requests, plus: may view requests where they are the resolved or role-eligible assignee on a pending stage, may approve or reject stages assigned to them, may comment on and view attachments for requests under their review, and may view the audit trail for requests they are or were assigned to. May not manage workflow definitions or view unrelated requests.

**Administrator** — May view all requests, comments, attachments, and the full audit trail; may create, edit (while inactive), and activate workflow definitions; may perform administrative moderation (soft-deleting a comment or attachment). Is explicitly **not** granted a shortcut to directly mutate `requests.status` or `workflow_stages.status` outside the Approval and Workflow endpoints, preserving a single, auditable code path for state transitions, per DSD Section 9.2.

### 6.3 Enforcement

Authorization is enforced twice, per the defense-in-depth principle shared by the ADD and DSD:

1. **Application Layer** — each Application Service method checks role and ownership before a mutation.
2. **Row-Level Security** — the same rule is independently enforced by PostgreSQL RLS policies (DSD Section 9), using the service-role/anon-key distinction (DSD Section 9.3).

---

## 7. API Versioning

### 7.1 URI Versioning

The API is versioned in the path: `/api/v1/...`.

### 7.2 Version Evolution Strategy

- **Additive changes** (a new optional field, a new endpoint, a new enum value clients are expected to tolerate) are made within `v1` without a version bump.
- **Breaking changes** require a new version prefix (`/api/v2/...`), published alongside `v1` for a deprecation window (Section 16), never as an in-place replacement.
- **No endpoint is ever silently repurposed** within a version.

---

## 8. Request Standards

| Aspect | Standard |
|---|---|
| HTTP Methods | `GET` (read), `POST` (create / non-idempotent action), `PATCH` (partial update), `DELETE` (soft-delete, where supported) |
| Payload Format | JSON, UTF-8 encoded |
| Timestamps | ISO-8601, UTC, explicit offset (`2026-07-08T14:32:00Z`) |
| Identifiers | UUID v4, canonical form (Section 3.8) |
| Content Type (request) | `Content-Type: application/json`, except file upload endpoints, which use `multipart/form-data` |
| Required Headers | `Authorization: Bearer <jwt>`; `Content-Type` as above |
| Optional Headers | `Accept: application/json`; `X-Request-Id` (client-supplied correlation id, echoed back per Section 27) |

---

## 9. Response Standards

Every successful response is a JSON object. Single-resource responses wrap the resource under `data`; list responses wrap an array under `data` and add pagination metadata (Section 12). Every response — success or error — includes a top-level `meta` object carrying `timestamp` and `request_id` (Section 27).

**Example — single resource:**

```json
{
  "data": {
    "id": "3f1a9c2e-1111-4a11-9b90-000000000010",
    "request_type": "expense_reimbursement",
    "title": "Client dinner reimbursement",
    "status": "in_review",
    "requester_id": "b3f1c2e4-2222-4a11-9b90-000000000001",
    "current_stage_id": "9a2b3c4d-3333-4a11-9b90-000000000020",
    "created_at": "2026-07-01T09:15:00Z",
    "updated_at": "2026-07-02T11:00:00Z"
  },
  "meta": { "timestamp": "2026-07-08T14:32:00Z", "request_id": "req_8f2c1a90" }
}
```

**Example — list resource:**

```json
{
  "data": [
    { "id": "3f1a9c2e-1111-4a11-9b90-000000000010", "title": "Client dinner reimbursement", "status": "in_review" },
    { "id": "6b7c8d9e-4444-4a11-9b90-000000000030", "title": "Laptop purchase request", "status": "pending" }
  ],
  "pagination": { "page": 1, "page_size": 20, "total_records": 47, "total_pages": 3 },
  "meta": { "timestamp": "2026-07-08T14:32:00Z", "request_id": "req_1c4a9f22" }
}
```

---

## 10. Resource Schemas

This section defines the canonical JSON shape of every resource returned by this API. Each schema corresponds directly to a Pydantic v2 model in `src/models` and a table in the DSD; the mapping from schema to model to database column is exact and one-to-one, per Section 28.

### 10.1 `Profile`

| Field | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | No | Equal to `auth.users.id` |
| `full_name` | string | No | |
| `role` | `user_role` | No | Section 4 |
| `department` | string | Yes | |
| `created_at` | datetime | No | |
| `updated_at` | datetime | No | |

### 10.2 `Request`

| Field | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | No | |
| `requester_id` | uuid | No | References `Profile.id` |
| `workflow_definition_id` | uuid | No | References `WorkflowDefinition.id` |
| `request_type` | string | No | |
| `title` | string | No | 1–200 chars |
| `description` | string | Yes | Up to 5,000 chars |
| `department` | string | Yes | |
| `status` | `request_status` | No | Section 4; see Section 20 for transitions |
| `current_stage_id` | uuid | Yes | References `WorkflowStage.id` |
| `deleted_at` | datetime | Yes | Section 23's soft-delete convention |
| `created_at` | datetime | No | |
| `updated_at` | datetime | No | |
| `completed_at` | datetime | Yes | |

### 10.3 `WorkflowStage`

| Field | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | No | |
| `request_id` | uuid | No | |
| `stage_order` | integer | No | `> 0` |
| `stage_name` | string | No | |
| `assigned_role` | `user_role` | Yes | |
| `assigned_to` | uuid | Yes | References `Profile.id` |
| `status` | `stage_status` | No | Section 4; see Section 20 for transitions |
| `decided_by` | uuid | Yes | |
| `decided_at` | datetime | Yes | |
| `decision_note` | string | Yes | Up to 1,000 chars |
| `created_at` | datetime | No | |

### 10.4 `Comment`

| Field | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | No | |
| `request_id` | uuid | No | |
| `author_id` | uuid | No | |
| `parent_comment_id` | uuid | Yes | |
| `body` | string | No | 1–5,000 chars |
| `deleted_at` | datetime | Yes | |
| `created_at` | datetime | No | |

### 10.5 `Attachment`

| Field | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | No | |
| `request_id` | uuid | No | |
| `uploaded_by` | uuid | No | |
| `file_name` | string | No | Sanitized (Section 23) |
| `content_type` | string | No | Allow-listed (Section 23) |
| `size_bytes` | integer | No | `> 0` |
| `storage_path` | string | No | Section 23 |
| `checksum_sha256` | string | No | Section 23 |
| `deleted_at` | datetime | Yes | |
| `created_at` | datetime | No | |

### 10.6 `Notification`

| Field | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | No | |
| `recipient_id` | uuid | No | |
| `request_id` | uuid | Yes | |
| `notification_type` | `notification_type` | No | Section 4 |
| `message` | string | No | |
| `is_read` | boolean | No | |
| `read_at` | datetime | Yes | |
| `email_sent` | boolean | No | |
| `email_sent_at` | datetime | Yes | |
| `archived_at` | datetime | Yes | Section 19.8.4/19.8.5 |
| `created_at` | datetime | No | |

### 10.7 `WorkflowDefinition`

| Field | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | No | |
| `request_type` | string | No | |
| `version` | integer | No | `> 0` |
| `definition` | object (JSON) | No | DSD Section 5 |
| `is_active` | boolean | No | |
| `created_by` | uuid | No | |
| `created_at` | datetime | No | |

### 10.8 `AuditLogEntry`

| Field | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | No | |
| `actor_id` | uuid | Yes | `null` for system-initiated actions |
| `request_id` | uuid | Yes | |
| `action` | string | No | Fixed action code, e.g. `REQUEST_CREATED` |
| `metadata` | object (JSON) | Yes | |
| `created_at` | datetime | No | |

---

## 11. Error Handling

### 11.1 Standard Error Format

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "The 'title' field is required.",
    "details": [ { "field": "title", "issue": "missing" } ]
  },
  "meta": { "timestamp": "2026-07-08T14:32:00Z", "request_id": "req_a91cde02" }
}
```

- `error.code` is a fixed, machine-readable string, stable across releases within `v1`.
- `error.message` is a human-readable summary, safe to display in the UI.
- `error.details` is optional, populated primarily for `422` validation failures.
- `meta.request_id` matches the identifier logged server-side (Section 27), so an error can be traced without exposing internal stack traces.

### 11.2 HTTP Status Code Reference

| Status | Meaning |
|---|---|
| `200 OK` | Successful read or update |
| `201 Created` | Successful creation |
| `204 No Content` | Successful action with no response body (e.g., logout, soft delete) |
| `400 Bad Request` | Malformed request (not valid JSON, wrong parameter type) |
| `401 Unauthorized` | Missing, expired, or invalid bearer token |
| `403 Forbidden` | Authenticated, but not permitted to perform this action |
| `404 Not Found` | Resource does not exist, or exists outside the caller's visibility |
| `409 Conflict` | Concurrent state change, per optimistic locking (DSD Section 3.9) |
| `422 Unprocessable Entity` | Well-formed request that fails validation or a business rule |
| `429 Too Many Requests` | Rate limit exceeded (Section 15) |
| `500 Internal Server Error` | Unexpected exception; never includes a stack trace |

### 11.3 Standardized Application Error Codes

Every `error.code` value used anywhere in this API is listed here exactly once; no endpoint specification in Section 19 introduces a code not in this table.

| `error.code` | HTTP Status | Meaning |
|---|---|---|
| `MALFORMED_REQUEST` | 400 | Request body is not valid JSON, or a query parameter has the wrong type |
| `AUTHENTICATION_REQUIRED` | 401 | Missing, expired, or invalid bearer token |
| `PERMISSION_DENIED` | 403 | Authenticated caller lacks the role/ownership required for this action |
| `RESOURCE_NOT_FOUND` | 404 | Resource does not exist or is outside the caller's visibility |
| `CONCURRENT_UPDATE` | 409 | Optimistic-locking `version` mismatch (DSD Section 3.9) |
| `DUPLICATE_ACTIVATION` | 409 | A competing workflow-definition activation was processed first (Section 19.9.3) |
| `STAGE_ALREADY_DECIDED` | 409 | An approve/reject was submitted against a stage no longer `pending` (Section 20.2) |
| `VALIDATION_ERROR` | 422 | Payload fails Pydantic model validation or a field-level rule (Section 22) |
| `INVALID_REQUEST_TYPE` | 422 | `request_type` does not match an active `WorkflowDefinition` |
| `INVALID_WORKFLOW_DEFINITION` | 422 | `definition` JSON fails structural validation (DSD Section 5) |
| `UNKNOWN_ASSIGNEE` | 422 | An `assigned_user_id` inside a workflow definition does not resolve to an existing profile |
| `INVALID_FILE_TYPE` | 422 | `content_type` is not on the upload allow-list (Section 23) |
| `FILE_TOO_LARGE` | 422 | `size_bytes` exceeds the configured maximum (Section 23) |
| `EMPTY_FILE` | 422 | `size_bytes` is not `> 0` (DSD Section 4.1) |
| `IMMUTABLE_FIELD` | 422 | A `PATCH` body includes a field that is never client-mutable (Section 3.6) |
| `PARENT_COMMENT_NOT_FOUND` | 422 | `parent_comment_id` does not reference an existing, non-deleted comment on the same request |
| `RATE_LIMITED` | 429 | The caller has exceeded the request rate in Section 15 |
| `INTERNAL_ERROR` | 500 | Unexpected exception; correlated via `request_id` in server logs |

### 11.4 Why Standardized Errors Improve Maintainability

A single error shape, and a single closed catalog of `error.code` values, means every client-side error handler in the Presentation Layer is written once, against `error.code`, rather than once per endpoint against ad hoc response shapes. It also means the security posture in Section 24 (never leaking stack traces, always logging a correlation id) is enforced structurally at the response-formatting boundary.

---

## 12. Pagination

Every list endpoint accepts `page` and `page_size` query parameters (defaults per Section 3.9) and returns a `pagination` object:

| Field | Description |
|---|---|
| `page` | 1-indexed page number requested |
| `page_size` | Records per page requested (default `20`, maximum `100`) |
| `total_records` | Total number of records matching the query, across all pages |
| `total_pages` | `ceil(total_records / page_size)` |

Pagination is mandatory on every list endpoint. Given the DSD's expected scale (100,000+ cumulative requests), an unpaginated endpoint would eventually return an unbounded payload and undermine the indexing strategy the DSD specifically built around bounded, filtered queries. A `page_size` above the maximum is rejected with `422` (`VALIDATION_ERROR`), not silently clamped.

---

## 13. Filtering and Sorting

| Parameter | Applies To | Example |
|---|---|---|
| `status` | Requests, Workflow Stages | `?status=pending` |
| `request_type` | Requests | `?request_type=expense_reimbursement` |
| `department` | Requests | `?department=finance` |
| `assigned_to` | Workflow Stages | `?assigned_to=me` |
| `is_read` | Notifications | `?is_read=false` |
| `notification_type` | Notifications | `?notification_type=assignment` |
| `is_archived` | Notifications | `?is_archived=true` (defaults to `false`, the active view) |
| `created_after` / `created_before` | Requests, Audit Logs | `?created_after=2026-06-01T00:00:00Z` |
| `search` | Requests | `?search=laptop` |
| `sort` | Most list endpoints | `?sort=-created_at` (Section 3.10) |

Multiple filters combine with logical AND. Unsupported query parameters are ignored rather than rejected, keeping the contract forward-compatible with future optional filters within `v1`.

---

## 14. Idempotency

### 14.1 Why POST Was Chosen for State-Changing Actions

Approve, reject, and workflow-definition activation are modeled as `POST` rather than `PUT`, because each is a **transition trigger** applied to an existing resource's state machine (Section 20), not a full replacement of the resource's representation. `PUT` implies "replace this resource with exactly this representation," which does not describe "advance this stage from pending to approved" — the caller does not supply the resulting resource state, they trigger a transition and the server computes the result. `POST` correctly signals a non-idempotent-by-default action, which this section then narrows with explicit, documented idempotency guarantees.

### 14.2 Duplicate Submission Behavior

| Endpoint | Duplicate Call Behavior |
|---|---|
| `POST /api/v1/requests` | Not idempotent by design — a second identical call creates a second, distinct request. The Presentation Layer is responsible for disabling a submit control after the first click; this API does not deduplicate on payload similarity, since two genuinely identical requests are a valid business scenario (e.g., two separate expense claims with the same title). |
| `POST /api/v1/workflow-stages/{id}/approve` | A duplicate call against the same `stage_id` after the first succeeded returns `409 CONCURRENT_UPDATE` (or the more specific `STAGE_ALREADY_DECIDED`, Section 11.3), never a second decision. |
| `POST /api/v1/workflow-stages/{id}/reject` | Same behavior as approve. |
| `POST /api/v1/workflow-definitions/{id}/activate` | A duplicate call after the first succeeded returns `409 DUPLICATE_ACTIVATION`, since the definition is already active and re-activating it is a no-op the server explicitly rejects rather than silently accepts, to keep the caller informed that no state actually changed on the second call. |

### 14.3 Retry Safety

A client may always safely retry a request that failed with a `5xx` status or a network-level timeout **before receiving a response**, for the endpoints in the table above, because the underlying operation is wrapped in a single database transaction (Section 21): a failure prior to commit leaves no partial state, and a retry either succeeds cleanly or is rejected with the appropriate `409` if the original attempt actually did commit before the response was lost in transit. A client must **not** retry a request that already received a definitive `2xx`, `4xx`, or business-level `409` response — those outcomes are final and a retry would either duplicate a resource (`POST /requests`) or be correctly rejected as a duplicate decision.

### 14.4 Interaction with Optimistic Locking

Idempotency and optimistic locking (DSD Section 3.9) are complementary, not redundant: optimistic locking protects against two *different* callers racing to update the same row, while the idempotency guarantees above protect against the *same* caller's request being retried or double-submitted. A retried approval that reaches the server after the original already committed is rejected by the same `version`-based check that would reject a genuinely different concurrent approver — from the database's perspective, a retry and a race are the same case, which is precisely why no separate deduplication mechanism (e.g., an idempotency-key header) is required for this baseline: the `version` check already provides it.

---

## 15. Rate Limiting

Rate limits are enforced per authenticated user (keyed on `profiles.id`), not per IP address, since this is an internally-authenticated system per the ADD's deployment model. **The one exception** (added in Milestone 9's hardening pass): `GET /api/v1/invitations/validate` and `POST /api/v1/invitations/accept` are this API's only unauthenticated endpoints — there is no `profiles.id` to key on, since the caller has no account yet — so those two routes alone are rate-limited per source IP address instead. Every other endpoint in this document, including every admin endpoint, remains user-keyed exactly as described above; this carve-out does not apply to them.

| Endpoint Category | Limit | Window |
|---|---|---|
| Read endpoints (`GET`) | 300 requests | per minute |
| Write endpoints (`POST`/`PATCH`/`DELETE`), general | 60 requests | per minute |
| `POST /api/v1/requests/{id}/attachments` (file upload) | 20 requests | per minute |
| `POST /api/v1/auth/login` | 10 requests | per 5 minutes (per email address, to slow credential-guessing attempts) |
| `GET /api/v1/notifications/unread-count` (polling endpoint) | 30 requests | per minute |
| `GET /api/v1/invitations/validate` + `POST /api/v1/invitations/accept` (public, unauthenticated — shared budget across both) | 20 requests | per 5 minutes, **per caller IP address** |

A caller exceeding a limit receives `429 RATE_LIMITED` (Section 11.3) with a `Retry-After` header indicating the number of seconds until the window resets. These figures are illustrative defaults sized for the SRS's stated scale (50 concurrent users) and are configuration, not code — they can be tuned per deployment without changing any endpoint's contract.

As of Milestone 13, every row above except `POST /api/v1/auth/login` has an actual server-side enforcement point (`app.api.rate_limiting`, an in-process, per-instance limiter — see that module's own docstring for its documented multi-instance-deployment limitation): `enforce_rate_limit` is attached to every authenticated router in `app.api.main` and is method-aware, splitting `GET`/`HEAD`/`OPTIONS` traffic into the read budget and everything else into the write budget; `enforce_upload_rate_limit` and `enforce_notification_poll_rate_limit` layer the two narrower, route-specific budgets on top of it for attachment upload/replace and the unread-count poll endpoint respectively; `enforce_invitation_rate_limit` (Milestone 9) remains the sole per-IP exception, for the two unauthenticated invitation routes. The `POST /api/v1/auth/login` row is not enforced because no such endpoint exists in this API — login is performed directly against Supabase Auth from the frontend (Section 5.2) — and is retained here only as a documented figure for a future first-party login endpoint, should one be added.

---

## 16. Deprecation Policy

### 16.1 Deprecated Endpoints

An endpoint is deprecated, never silently removed. A deprecated endpoint continues to function exactly as documented for the remainder of its sunset period (Section 16.2).

### 16.2 Sunset Period

A deprecated endpoint remains available for a minimum of one full minor documentation cycle after the replacement is published, giving the Presentation Layer (the only current consumer) time to migrate before removal — consistent with the DSD's own forward-only, non-destructive philosophy applied to the API surface.

### 16.3 Warning Headers

A deprecated endpoint includes a `Deprecation: true` response header and a `Sunset: <date>` header (RFC 8594 style) on every response, so that deprecation is visible in tooling (browser network tab, API client) without requiring the caller to consult this document first.

### 16.4 Migration Notices

Alongside the headers above, this document's changelog (maintained at the top of this file, per its `Version` field) records the replacement endpoint and the reason for deprecation at the time it is announced, so the migration path is documented in the same place the original contract was.

### 16.5 Removal Policy

An endpoint is only removed from the specification once its sunset period has fully elapsed and no traffic to it has been observed in the preceding period, per Section 27's observability tooling. Removal is always a version-scoped event (Section 7) — an endpoint present in `v1` is never removed from `v1`; it is dropped only when `v1` itself is retired in favor of a later major version.

---

## 17. Request Lifecycle Diagram

The diagram below traces a single request through the API surface, from submission to completion, matching the ADD's Request Lifecycle step-by-step, with each step's corresponding endpoint noted.

```
 1. POST /api/v1/requests
    └─ RequestService validates payload, resolves active WorkflowDefinition,
       creates Request + first WorkflowStage in one transaction, writes
       AuditLogEntry, dispatches "assignment" Notification.
                              │
                              ▼
 2. GET /api/v1/requests/{id}/workflow/current
    └─ Approver's Presentation Layer polls or loads their queue via
       GET /api/v1/approvals/pending.
                              │
                              ▼
 3. POST /api/v1/requests/{id}/comments   (optional, any number of times)
    └─ CommentService records clarifying discussion; each call writes its
       own AuditLogEntry independently of the workflow's progress.
                              │
                              ▼
 4. POST /api/v1/requests/{id}/attachments   (optional, any number of times)
    └─ AttachmentService writes to Supabase Storage, then inserts metadata
       and an AuditLogEntry in one transaction (Section 23).
                              │
                              ▼
 5. POST /api/v1/workflow-stages/{stage_id}/approve   (or /reject)
    └─ ApprovalService decides the current stage, advances
       current_stage_id to the next stage OR marks the Request completed/
       rejected, writes an AuditLogEntry, dispatches a "decision"
       Notification to the requester and, if applicable, an "assignment"
       Notification to the next stage's assignee.
                              │
              (repeat steps 2–5 for each remaining stage)
                              │
                              ▼
 6. Terminal state reached: Request.status = completed | rejected
    └─ GET /api/v1/requests/{id} now returns the terminal status;
       GET /api/v1/requests/{id}/workflow/history returns the full
       decided-stage record; GET /api/v1/requests/{id}/audit-log returns
       the complete, immutable history of every step above.
```

---

## 18. Endpoint Summary Table

| Method | Path | Purpose | Min. Role |
|---|---|---|---|
| POST | `/api/v1/auth/login` | Obtain a session | None |
| POST | `/api/v1/auth/logout` | End a session | employee |
| GET | `/api/v1/auth/me` | Current user | employee |
| GET | `/api/v1/profiles/{id}` | Retrieve profile | employee |
| PATCH | `/api/v1/profiles/{id}` | Update profile | employee (self) / admin |
| POST | `/api/v1/requests` | Create request | employee |
| GET | `/api/v1/requests` | List requests | employee |
| GET | `/api/v1/requests/{id}` | Get request | employee |
| PATCH | `/api/v1/requests/{id}` | Update request | employee (requester) |
| DELETE | `/api/v1/requests/{id}` | Withdraw request (soft delete) | employee (requester) / admin |
| GET | `/api/v1/requests/search` | Search requests | employee |
| GET | `/api/v1/requests/{id}/workflow` | Full workflow | employee |
| GET | `/api/v1/requests/{id}/workflow/current` | Current stage | employee |
| GET | `/api/v1/requests/{id}/workflow/history` | Decided stages | employee |
| POST | `/api/v1/workflow-stages/{id}/approve` | Approve stage | approver |
| POST | `/api/v1/workflow-stages/{id}/reject` | Reject stage | approver |
| GET | `/api/v1/approvals/pending` | My pending approvals | approver |
| POST | `/api/v1/requests/{id}/comments` | Create/reply to comment | employee |
| GET | `/api/v1/requests/{id}/comments` | List comments | employee |
| DELETE | `/api/v1/comments/{id}` | Remove comment (soft delete) | admin |
| POST | `/api/v1/requests/{id}/attachments` | Upload attachment | employee |
| GET | `/api/v1/attachments/{id}/download` | Download attachment | employee |
| GET | `/api/v1/requests/{id}/attachments` | List attachments | employee |
| DELETE | `/api/v1/attachments/{id}` | Remove attachment (soft delete) | employee (uploader) / admin |
| GET | `/api/v1/notifications` | List my notifications | employee |
| PATCH | `/api/v1/notifications/{id}/read` | Mark read | employee |
| PATCH | `/api/v1/notifications/read-all` | Mark all read | employee |
| PATCH | `/api/v1/notifications/{id}/archive` | Archive | employee (recipient only) |
| PATCH | `/api/v1/notifications/{id}/unarchive` | Restore an archived notification | employee (recipient only) |
| GET | `/api/v1/notifications/unread-count` | Unread count | employee |
| POST | `/api/v1/workflow-definitions` | Create definition | admin |
| PATCH | `/api/v1/workflow-definitions/{id}` | Edit inactive definition | admin |
| POST | `/api/v1/workflow-definitions/{id}/activate` | Activate definition | admin |
| GET | `/api/v1/workflow-definitions` | List definitions | employee (active only) / admin (all) |
| GET | `/api/v1/requests/{id}/audit-log` | Request audit trail | employee |
| GET | `/api/v1/audit-logs` | Org-wide audit search | admin |
| GET | `/api/v1/search` | Global fuzzy search across every entity | employee (scoped per entity type; `user` results admin only) |

---

## 19. Endpoint Specifications

Every endpoint below follows the conventions fixed in Section 3 and operates under the base path `/api/v1`. Unless otherwise noted, all endpoints require authentication (Section 5); "Authorization" states the additional role/ownership requirement.

### 19.1 Authentication

#### 19.1.1 `POST /api/v1/auth/login`

**Purpose:** Exchange user credentials for a Supabase-issued session.
**Authorization:** None.
**Headers:** `Content-Type: application/json`
**Request Body:** `{ "email": "jane.doe@example.com", "password": "•••••••••" }`
**Validation Rules:** `email` syntactically valid; `password` non-empty.
**Example Response (200):**
```json
{
  "data": {
    "access_token": "eyJhbGciOi...",
    "refresh_token": "v1.MgTz...",
    "expires_in": 3600,
    "user": { "id": "b3f1c2e4-2222-4a11-9b90-000000000001", "email": "jane.doe@example.com", "role": "employee" }
  },
  "meta": { "timestamp": "2026-07-08T14:32:00Z", "request_id": "req_10a1" }
}
```
**Status Codes:** `200`; `400 MALFORMED_REQUEST`; `401 AUTHENTICATION_REQUIRED`.
**Idempotency:** Not idempotent — each call issues a new token pair.
**Related Components:** `AuthService`.

#### 19.1.2 `POST /api/v1/auth/logout`

**Purpose:** Invalidate the current session's refresh token.
**Authorization:** Authenticated (any role).
**Status Codes:** `204`; `401 AUTHENTICATION_REQUIRED`.
**Related Components:** `AuthService`.

#### 19.1.3 `GET /api/v1/auth/me`

**Purpose:** Return the profile and role of the currently authenticated caller.
**Authorization:** Authenticated (any role).
**Example Response (200):** see `Profile` schema, Section 10.1.
**Status Codes:** `200`; `401 AUTHENTICATION_REQUIRED`.
**Related Components:** `AuthService`, `Profile`.

### 19.2 User Profile

#### 19.2.1 `GET /api/v1/profiles/{id}`

**Purpose:** Retrieve a user's profile.
**Authorization:** Self, `admin`, or an `approver` reviewing that user's request (name/department only).
**Status Codes:** `200`; `403 PERMISSION_DENIED`; `404 RESOURCE_NOT_FOUND`.
**Related Components:** `AuthService`, `Profile`.

#### 19.2.2 `PATCH /api/v1/profiles/{id}`

**Purpose:** Update mutable profile fields.
**Authorization:** Self may update `full_name`; only `admin` may update `role` or `department`.
**Request Body:** `{ "role": "approver" }`
**Validation Rules:** `role`, if present, must be a valid `user_role` value (Section 4) or `422 VALIDATION_ERROR`.
**Status Codes:** `200`; `403`; `404`; `409 CONCURRENT_UPDATE`; `422`.
**Related Components:** `AuthService`, `Profile`.

### 19.3 Requests

#### 19.3.1 `POST /api/v1/requests`

**Purpose:** Submit a new business request.
**Authorization:** Any authenticated user.
**Request Body:**
```json
{ "request_type": "expense_reimbursement", "title": "Client dinner reimbursement", "description": "Dinner with prospective client.", "department": "sales" }
```
**Validation Rules:** `request_type` must match an active `WorkflowDefinition` or `422 INVALID_REQUEST_TYPE`; `title` required, 1–200 chars; `description` optional, ≤5,000 chars.
**Example Response (201):** see `Request` schema, Section 10.2.
**Status Codes:** `201`; `400`; `401`; `422 INVALID_REQUEST_TYPE` / `VALIDATION_ERROR`.
**Idempotency:** Not idempotent (Section 14.2).
**Transaction Guarantee:** See Section 21.1.
**Related Components:** `RequestService`, `WorkflowEngine`, `AuditService`, `NotificationService`.

#### 19.3.2 `GET /api/v1/requests`

**Purpose:** List requests visible to the caller.
**Authorization:** `employee` — own only; `approver` — own plus assigned; `admin` — all.
**Query Parameters:** `status`, `request_type`, `department`, `created_after`, `created_before`, `sort` (default `-created_at`), `page`, `page_size`.
**Status Codes:** `200`; `401`; `422` (invalid filter value).
**Related Components:** `RequestService`.

#### 19.3.3 `GET /api/v1/requests/{id}`

**Purpose:** Retrieve a single request.
**Authorization:** Requester, assigned approver, or `admin`.
**Status Codes:** `200`; `404 RESOURCE_NOT_FOUND` (out-of-scope requests return `404`, not `403`, per Section 11.2); `401`.
**Related Components:** `RequestService`.

#### 19.3.4 `PATCH /api/v1/requests/{id}`

**Purpose:** Update editable fields while the request is still `pending`.
**Authorization:** Requester only, only while `status = pending`.
**Request Body:** Any subset of `title`, `description`, `department`.
**Validation Rules:** `status`/`current_stage_id` present in body → `422 IMMUTABLE_FIELD` (Section 3.6).
**Status Codes:** `200`; `403`; `404`; `409 CONCURRENT_UPDATE`; `422`.
**Transaction Guarantee:** See Section 21.2.
**Related Components:** `RequestService`.

#### 19.3.5 `DELETE /api/v1/requests/{id}`

**Purpose:** Withdraw a request (soft delete, DSD Section 3.10).
**Authorization:** Requester, only while `status = pending`; or `admin`, any status.
**Status Codes:** `204`; `403`; `404`; `409`.
**Transaction Guarantee:** See Section 21.3.
**Related Components:** `RequestService`, `AuditService`.

#### 19.3.6 `GET /api/v1/requests/search`

**Purpose:** Free-text search across the caller's visible requests. Implemented as the `search` parameter on the List endpoint (Section 19.3.2); documented separately only to make the capability independently reviewable, per the resource-oriented principle in Section 2.
**Example Request:** `GET /api/v1/requests/search?q=laptop&page=1&page_size=20`
**Status Codes:** `200`; `401`; `422` (missing `q`).
**Related Components:** `RequestService`, `AnalyticsService`.

### 19.4 Workflow

#### 19.4.1 `GET /api/v1/requests/{id}/workflow`

**Purpose:** Full, ordered list of `WorkflowStage` rows for a request.
**Authorization:** Same as `GET /api/v1/requests/{id}`.
**Status Codes:** `200`; `403`/`404`; `401`.
**Related Components:** `ApprovalService`, `WorkflowEngine`.

#### 19.4.2 `GET /api/v1/requests/{id}/workflow/current`

**Purpose:** The stage currently awaiting action.
**Status Codes:** `200`; `204` (no current stage — completed); `403`/`404`.
**Related Components:** `ApprovalService`.

#### 19.4.3 `GET /api/v1/requests/{id}/workflow/history`

**Purpose:** Decided stages only, ordered by `stage_order`.
**Status Codes:** `200`; `403`/`404`.
**Related Components:** `ApprovalService`.

### 19.5 Approval

#### 19.5.1 `POST /api/v1/workflow-stages/{stage_id}/approve`

**Purpose:** Record an approval, advancing the request per Section 20.2.
**Authorization:** `approver`/`admin`, resolved assignee or role-eligible, only while `status = pending`.
**Request Body:** `{ "decision_note": "Approved — within policy limits.", "expected_version": 1 }`
**Validation Rules:** `decision_note` optional, ≤1,000 chars; `expected_version` optional, used for an explicit conflict check (Section 14.4).
**Status Codes:** `200`; `403`; `404`; `409 CONCURRENT_UPDATE` / `STAGE_ALREADY_DECIDED`; `422`.
**Idempotency:** See Section 14.2–14.4.
**Transaction Guarantee:** See Section 21.4.
**Related Components:** `ApprovalService`, `WorkflowEngine`, `AuditService`, `NotificationService`.

#### 19.5.2 `POST /api/v1/workflow-stages/{stage_id}/reject`

**Purpose:** Record a rejection, terminating the request's workflow.
**Authorization:** Same as Approve.
**Request Body:** `{ "decision_note": "Missing required receipt.", "expected_version": 1 }`
**Validation Rules:** `decision_note` is **required** on rejection (unlike approval), enforced as a business rule.
**Status Codes:** `200`; `403`; `404`; `409`; `422`.
**Transaction Guarantee:** See Section 21.4.
**Related Components:** `ApprovalService`, `AuditService`, `NotificationService`.

#### 19.5.3 `GET /api/v1/approvals/pending`

**Purpose:** List stages awaiting the caller's decision.
**Authorization:** `approver`/`admin`.
**Query Parameters:** `page`, `page_size`, `sort` (default oldest-first).
**Status Codes:** `200`; `401`; `403`.
**Related Components:** `ApprovalService`.

### 19.6 Comments

#### 19.6.1 `POST /api/v1/requests/{id}/comments`

**Purpose:** Add a comment, or reply to one (via `parent_comment_id`).
**Authorization:** Requester, assigned approver, or `admin`.
**Request Body:** `{ "body": "Please attach the itemized receipt.", "parent_comment_id": null }`
**Validation Rules:** `body` required, 1–5,000 chars; `parent_comment_id`, if present, must reference an existing, non-deleted comment on the same request, or `422 PARENT_COMMENT_NOT_FOUND`.
**Status Codes:** `201`; `403`/`404`; `422`.
**Transaction Guarantee:** See Section 21.5.
**Related Components:** `CommentService`, `AuditService`.

#### 19.6.2 `GET /api/v1/requests/{id}/comments`

**Purpose:** List the comment thread in creation order.
**Status Codes:** `200`; `403`/`404`.
**Related Components:** `CommentService`.

#### 19.6.3 `DELETE /api/v1/comments/{id}`

**Purpose:** Administrative removal (soft delete, DSD Section 3.10).
**Authorization:** `admin` only.
**Status Codes:** `204`; `403`; `404`.
**Related Components:** `CommentService`, `AuditService`.

### 19.7 Attachments

See Section 23 for the full file-handling discussion (sanitization, duplicates, MIME sniffing, checksums, future virus scanning, orphan cleanup).

#### 19.7.1 `POST /api/v1/requests/{id}/attachments`

**Purpose:** Upload a file against a request.
**Authorization:** Requester, assigned approver, or `admin`.
**Headers:** `Content-Type: multipart/form-data`
**Request Body:** Multipart form, single `file` part.
**Validation Rules:** Section 23.
**Status Codes:** `201`; `403`/`404`; `422 INVALID_FILE_TYPE` / `FILE_TOO_LARGE` / `EMPTY_FILE`.
**Transaction Guarantee:** See Section 21.6.
**Related Components:** `AttachmentService`, `AuditService`.

#### 19.7.2 `GET /api/v1/attachments/{id}/download`

**Purpose:** Retrieve a short-lived signed Storage URL.
**Status Codes:** `200`; `403`/`404`.
**Related Components:** `AttachmentService`.

#### 19.7.3 `GET /api/v1/requests/{id}/attachments`

**Purpose:** List attachment metadata.
**Status Codes:** `200`; `403`/`404`.
**Related Components:** `AttachmentService`.

#### 19.7.4 `DELETE /api/v1/attachments/{id}`

**Purpose:** Remove an attachment (soft delete).
**Authorization:** Uploader (while request is `pending`), or `admin`.
**Status Codes:** `204`; `403`; `404`.
**Related Components:** `AttachmentService`, `AuditService`.

### 19.8 Notifications

#### 19.8.1 `GET /api/v1/notifications`

**Purpose:** List the caller's own notifications.
**Query Parameters:** `is_read`, `notification_type`, `is_archived` (default `false`), `page`, `page_size`, `sort` (default `-created_at`).
**Status Codes:** `200`; `401`.
**Related Components:** `NotificationService`.

#### 19.8.2 `PATCH /api/v1/notifications/{id}/read`

**Purpose:** Mark a notification read.
**Authorization:** Recipient only.
**Status Codes:** `200` (idempotent — Section 2); `403`; `404`.
**Related Components:** `NotificationService`.

#### 19.8.3 `GET /api/v1/notifications/unread-count`

**Purpose:** Return an unread count for a lightweight UI badge. Excludes archived notifications (Section 19.8.4/19.8.5) — an archived notification never contributes to this count.
**Example Response (200):** `{ "data": { "unread_count": 4 }, "meta": { ... } }`
**Status Codes:** `200`; `401`.
**Related Components:** `NotificationService`.

#### 19.8.4 `PATCH /api/v1/notifications/{id}/archive`

**Purpose:** Archive a notification, removing it from the recipient's default (active) view without deleting it.
**Authorization:** Recipient only — not even an administrator may archive another user's notification.
**Status Codes:** `200` (idempotent — archiving an already-archived notification is a no-op that still returns `200`); `403`; `404`.
**Related Components:** `NotificationService`.

#### 19.8.5 `PATCH /api/v1/notifications/{id}/unarchive`

**Purpose:** Restore a previously archived notification to the recipient's default view.
**Authorization:** Recipient only.
**Status Codes:** `200` (idempotent); `403`; `404`.
**Related Components:** `NotificationService`.

#### 19.8.6 `PATCH /api/v1/notifications/read-all`

**Purpose:** Mark every one of the caller's currently unread notifications as read in a single call.
**Authorization:** Caller, for their own notifications only.
**Example Response (200):** `{ "data": { "updated_count": 3 }, "meta": { ... } }`
**Status Codes:** `200` (idempotent — returns `updated_count: 0` if nothing was unread); `401`.
**Related Components:** `NotificationService`.

### 19.9 Workflow Definitions

#### 19.9.1 `POST /api/v1/workflow-definitions`

**Purpose:** Create a new definition version (DSD Section 5).
**Authorization:** `admin` only.
**Validation Rules:** `definition.stages` non-empty array; each entry requires `order` (`>0`, unique) and `name`; every `assigned_user_id` must resolve to an existing profile or `422 UNKNOWN_ASSIGNEE`.
**Status Codes:** `201`; `403`; `422 INVALID_WORKFLOW_DEFINITION` / `UNKNOWN_ASSIGNEE`.
**Related Components:** `WorkflowEngine`.

#### 19.9.2 `PATCH /api/v1/workflow-definitions/{id}`

**Purpose:** Edit a definition not yet activated.
**Authorization:** `admin` only.
**Status Codes:** `200`; `403`; `404`; `409` (already active or referenced by a request).
**Related Components:** `WorkflowEngine`.

#### 19.9.3 `POST /api/v1/workflow-definitions/{id}/activate`

**Purpose:** Activate a version, deactivating the prior active version atomically.
**Authorization:** `admin` only.
**Status Codes:** `200`; `403`; `404`; `409 DUPLICATE_ACTIVATION`.
**Idempotency:** See Section 14.2.
**Transaction Guarantee:** See Section 21.7.
**Related Components:** `WorkflowEngine`, `AuditService`.

#### 19.9.4 `GET /api/v1/workflow-definitions`

**Purpose:** List definitions.
**Authorization:** Any authenticated user (active only); `admin` (all, including drafts).
**Status Codes:** `200`; `403` (non-admin requesting inactive versions).
**Related Components:** `WorkflowEngine`.

### 19.10 Audit Logs

#### 19.10.1 `GET /api/v1/requests/{id}/audit-log`

**Purpose:** Full audit trail for a request, chronological.
**Authorization:** Same visibility as the parent request.
**Status Codes:** `200`; `403`/`404`.
**Related Components:** `AuditService`.

#### 19.10.2 `GET /api/v1/audit-logs`

**Purpose:** Organization-wide audit search.
**Authorization:** `admin` only.
**Query Parameters:** `actor_id`, `action`, `created_after`, `created_before`, `page`, `page_size`.
**Status Codes:** `200`; `403`.
**Related Components:** `AuditService`. No `PATCH`/`DELETE` route exists for this resource anywhere in this API, matching the DSD's `INSERT`/`SELECT`-only database grants.

### 19.11 Global Search

#### 19.11.1 `GET /api/v1/search`

**Purpose:** Fuzzy, filterable search across requests, the caller's own pending approvals, workflow definitions, comments, audit entries, and (administrator only) user profiles — one ranked, combined result list, not a separate resource per entity type.
**Authorization:** Every authenticated role; each entity type is scoped to exactly what that caller could already see through its own dedicated endpoint (Sections 19.3, 19.5, 19.6, 19.9, 19.10) — this endpoint grants no visibility beyond that. `entity_type=user` results are silently omitted for a non-administrator rather than rejected with `403`, so a shared filter selection degrades gracefully across roles instead of erroring.
**Query Parameters:** `q` (required, the search term), `entity_type` (repeatable — `request`, `approval`, `workflow`, `user`, `comment`, `audit_entry`; defaults to every type the caller's role can ever match).
**Example Response (200):** `{ "data": [ { "entity_type": "request", "id": "...", "title": "...", "subtitle": "...", "snippet": "...with the **match** highlighted...", "score": 0.91, "created_at": "...", "request_id": "..." }, ... ], "meta": { ... } }`
**Status Codes:** `200`; `400 VALIDATION_ERROR` (empty `q`); `401`.
**Related Components:** `GlobalSearchService`, composing `RequestService`, `ApprovalService`, and `WorkflowDefinitionService` directly (each already scoped correctly per role), plus `CommentRepository`/`AuditRepository`/`ProfileRepository` directly where no dedicated service method searches across more than one request or user at a time.
**Matching:** A case-insensitive substring (`ILIKE`) query narrows each entity type at the database — the same mechanism `search_requests` (Section 19.3.6) already uses — except `approval`, whose candidates are the caller's own bounded pending-approval queue, scored entirely in application code (no database prefilter exists for that entity type). Every result is additionally scored for typo tolerance via a dependency-free string-similarity function, not a database full-text-search or trigram index — no such index is provisioned in this schema (Section 3, Database Schema Design Document). This is real typo tolerance on an already-authorized, bounded candidate set, not a true fuzzy search across an entire table.
**Not paginated.** Each entity type is capped at a fixed result count per request; this endpoint is a quick, cross-entity lookup, not an exhaustive browse — a caller wanting every match within one entity type uses that entity's own paginated endpoint instead.

---

## 20. State Transition Tables

### 20.1 `Request.status`

| From | To | Trigger |
|---|---|---|
| `pending` | `in_review` | First stage approved (further stages remain) |
| `pending` | `rejected` | First stage rejected |
| `pending` | `completed` | First (and only) stage approved |
| `in_review` | `in_review` | An intermediate stage approved (further stages remain) |
| `in_review` | `completed` | Final stage approved |
| `in_review` | `rejected` | Any stage rejected |
| any (`pending`, `in_review`) | *(soft-deleted)* | `DELETE /requests/{id}` — `deleted_at` set; `status` itself is unchanged, since withdrawal is orthogonal to the approval outcome |

`approved` is reserved for a request-level status only in the sense that `completed` is EAH's terminal "approved" state — no request row transitions through a bare `approved` status distinct from `completed`; the enum value exists for forward compatibility with a possible future "approved, pending final disbursement" distinction (Section 32) and is not reachable from any endpoint in this baseline.

No transition ever moves backward (e.g., `completed` → `in_review`); every mutation of `status` is issued exclusively by `ApprovalService` (Section 19.5), never by a direct client `PATCH`.

### 20.2 `WorkflowStage.status`

| From | To | Trigger |
|---|---|---|
| `pending` | `approved` | `POST /workflow-stages/{id}/approve` |
| `pending` | `rejected` | `POST /workflow-stages/{id}/reject` |
| `pending` | `skipped` | Workflow Engine determines this stage's condition does not apply (definition-driven, DSD Section 5) |

`approved`, `rejected`, and `skipped` are all terminal for that specific stage row — a decided stage is never revisited or reopened; a correction is handled at the request level (see the ADD's Comment System for clarifying discussion) rather than by mutating a historical stage decision, consistent with the audit-integrity principle shared across the ADD and DSD.

---

## 21. Endpoint Transaction Guarantees

Every mutating endpoint below is backed by a single PostgreSQL transaction issued from the Repository Layer, per DSD Section 11 — the database is never left in a state where only part of the described effect has been committed.

**21.1 `POST /api/v1/requests`** — Insert `Request`; insert first `WorkflowStage`; update `Request.current_stage_id`; insert `AuditLogEntry`. All four statements commit together or not at all (DSD Section 11, "Request creation").

**21.2 `PATCH /api/v1/requests/{id}`** — Update guarded by `version` (optimistic locking, DSD Section 3.9); single-row update, single transaction.

**21.3 `DELETE /api/v1/requests/{id}`** — Update `deleted_at`/`deleted_by`, guarded by `version`; the underlying row and every table referencing it (comments, attachments, audit_logs, workflow_stages) remain intact, per the `RESTRICT` foreign key behavior in DSD Section 4.

**21.4 `POST /api/v1/workflow-stages/{id}/approve` and `/reject`** — Update the current `WorkflowStage`; insert the next `WorkflowStage` row (approve, if further stages remain) or update `Request.status`/`completed_at` (approve on final stage, or reject); update `Request.current_stage_id`; insert `AuditLogEntry`. All committed atomically (DSD Section 11, "Approval decision") — a reader never observes a stage marked `approved` while the request still points to it as current.

**21.5 `POST /api/v1/requests/{id}/comments`** — Insert `Comment`; insert `AuditLogEntry`, atomically (DSD Section 11, "Comment creation").

**21.6 `POST /api/v1/requests/{id}/attachments`** — Write to Supabase Storage first (outside PostgreSQL); only on success, insert `Attachment` and `AuditLogEntry` in one transaction (DSD Section 11, "Attachment upload"). No `Attachment` row is ever committed for a file that does not exist in Storage.

**21.7 `POST /api/v1/workflow-definitions/{id}/activate`** — Update the previously active row's `is_active` to `false`; insert or update the target row's `is_active` to `true`, atomically (DSD Section 11, "Workflow definition activation") — no window exists in which two versions of the same `request_type` are simultaneously active.

**21.8 `PATCH /api/v1/notifications/{id}/read`** and **`PATCH /api/v1/profiles/{id}`** — Single-row updates guarded by their respective `version`/idempotency rules (Sections 3.6, 14); no multi-table coordination is required.

Read-only endpoints are not listed here; they execute under PostgreSQL's default read-committed isolation and require no explicit transaction boundary beyond the single query itself.

---

## 22. Validation Rules

| Data Type | Rule |
|---|---|
| UUIDs | Well-formed UUID v4; a malformed path parameter returns `400 MALFORMED_REQUEST`, not `404`, since the request never reached a resource lookup. |
| Strings | Explicit, documented maximum length per field (Section 10); exceeding it returns `422 VALIDATION_ERROR` naming the field in `error.details`. |
| Dates | ISO-8601 with explicit UTC offset or `Z`; a naive timestamp is rejected with `422`, never assumed to be UTC. |
| File Uploads | Section 23. |
| JSON Payloads | Must parse as valid JSON with `Content-Type: application/json`; otherwise `400 MALFORMED_REQUEST`, prior to field-level validation. |
| Business Rules | State-dependent rules (e.g., "a stage cannot be decided twice") are evaluated by the Application Layer and reported as `409` (conflict with concurrent state) or `422` (rule inherent to the request itself), per Section 11.2. |

Every rule above is enforced by the same Pydantic v2 models described in the ADD's Domain Layer; this API surfaces the outcome of validation that already happens once, at the model-construction boundary.

---

## 23. File Upload Handling

This section expands the attachment endpoints in Section 19.7 with the full handling discipline applied to every uploaded file.

**Filename sanitization.** `file_name` as supplied by the client is never used verbatim in a storage path. Path separators (`/`, `\`), null bytes, and control characters are stripped; the sanitized name is what appears in `storage_path` (DSD Section 7.3: `attachments/{request_id}/{attachment_id}_{sanitized_file_name}`) and in API responses, while the original, as-submitted name is preserved only in the `file_name` field for display purposes.

**Duplicate filenames.** Because `storage_path` is namespaced by both `request_id` and the newly generated `attachment_id` (DSD Section 7.3), two uploads with an identical `file_name` on the same request never collide — each receives its own unique path and its own `attachments` row. No "overwrite" semantics exist anywhere in this API; a same-named re-upload is always a new attachment, never a replacement of a prior one.

**MIME sniffing.** The client-supplied `Content-Type` is treated as a hint, not a trusted assertion: `AttachmentService` inspects the file's actual byte signature (magic bytes) server-side and rejects a mismatch between the declared and detected type with `422 INVALID_FILE_TYPE`, closing off a class of attack where a disallowed file type is disguised with an allow-listed `Content-Type` header.

**Checksum validation.** A SHA-256 checksum is computed over the file content at upload time and stored as `attachments.checksum_sha256` (Section 10.5). This provides an integrity check for the download path (a client can verify the downloaded bytes match what was uploaded) and a deduplication signal for future tooling (Section 32), without this baseline implementing deduplication itself.

**Virus scanning (future).** No virus/malware scanning is performed in this baseline, consistent with the fixed technology stack introducing no scanning service. The `attachments` schema and `AttachmentService`'s upload sequence are positioned so that a scanning step could be inserted between the Storage write and the `attachments` row insert (Section 21.6) in a future iteration — for example, gating the transaction on a clean scan result — without changing the endpoint's contract or request/response shape.

**Orphan cleanup.** Because the Storage write happens before the database transaction (Section 21.6), a failure between the two steps (e.g., a crash after the Storage write but before the `INSERT` commits) can leave a Storage object with no corresponding `attachments` row. Such orphans are identified by a periodic APScheduler job (per the ADD's Scheduler component) that compares Storage bucket contents against `attachments.storage_path` values and removes objects with no matching row older than a configured grace period — the same in-process, non-Celery scheduling mechanism already used for escalation and reminder jobs, introducing no new infrastructure.

---

## 24. Security Considerations

**JWT validation.** Every request is authenticated per Section 5 before any Application Service method executes.

**Input validation.** Every payload is parsed into a Pydantic v2 model before reaching business logic (Section 22).

**SQL injection prevention.** All persistence goes through the Repository Layer's parameterized Supabase client calls; no endpoint constructs a query from unsanitized input.

**XSS prevention.** Free-text fields are stored and returned as plain text; rendering/escaping is the Presentation Layer's responsibility.

**CSRF considerations.** Every request carries an explicit bearer token (Section 5.2) rather than relying on an ambient cookie session, so this API is not vulnerable to classic CSRF.

**Rate limiting.** Section 15.

**Authorization.** Enforced twice — Application Layer and RLS — per Section 6.3.

**Sensitive data handling.** No endpoint returns another user's authentication credentials; `Profile` responses never include Supabase Auth internals.

**Secure file uploads.** Section 23.

**Audit logging.** Every mutating endpoint writes a corresponding `AuditLogEntry` within the same transaction that performs the mutation (Section 21); no mutating endpoint is unreconstructable from the audit trail.

---

## 25. Performance Considerations and Expectations

### 25.1 Design-Level Considerations

**Pagination.** Mandatory on all list endpoints (Section 12).
**Caching opportunities.** `GET /api/v1/workflow-definitions?is_active=true` and `GET /api/v1/auth/me` are natural candidates for short-lived, per-process in-memory caching — no distributed cache is introduced.
**Payload size.** List endpoints return summary fields only; full detail is available via the single-resource `GET`.
**Efficient endpoint design.** Every filter in Section 13 corresponds to an index already specified in the DSD (Sections 10.1–10.2).
**Batch operations.** No bulk-mutation endpoint is introduced; each approval remains individually authorized and audited (Section 21.4).
**Connection reuse.** This API reuses the same Supabase connection-pooling behavior already described in the ADD and DSD.

### 25.2 Expected Latency and Throughput

| Operation Class | Expected p95 Latency | Basis |
|---|---|---|
| Single-resource `GET` (indexed lookup) | < 150 ms | Single-row, primary-key or unique-index read (DSD Section 10.1) |
| List `GET` (filtered, paginated) | < 300 ms | Composite-index-backed query (DSD Section 10.2), bounded by `page_size ≤ 100` |
| `POST /requests`, `approve`, `reject` | < 400 ms | Multi-statement transaction (Section 21), still within a single round trip to Supabase |
| File upload (`POST /attachments`) | < 1,500 ms for files ≤5 MB | Dominated by the Storage write, not the metadata insert |

These figures are targets consistent with the DSD's stated scale (100,000+ requests, 50 concurrent users), not contractual SLAs; they are the basis against which Section 27's metrics are expected to be evaluated.

---

## 26. Non-Functional Guarantees

| Property | Guarantee |
|---|---|
| Consistency model | Strong consistency for all reads and writes — there is no eventual-consistency window anywhere in this API, since every write is a committed PostgreSQL transaction and every read observes the database's current committed state (read-committed isolation, per Section 21). |
| Transaction isolation | PostgreSQL default `READ COMMITTED` for all operations; combined with optimistic locking (DSD Section 3.9) for the specific rows subject to concurrent-update risk, per Section 14.4. |
| Retry behavior | Safe per Section 14.3 for the specific endpoints and conditions documented there; not a blanket guarantee for every endpoint. |
| Timeout policy | A request that has not completed within 30 seconds is abandoned server-side and the caller receives `500 INTERNAL_ERROR`; the client is expected to check the resource's actual state (e.g., `GET /requests/{id}`) before retrying, per Section 14.3, rather than assume the timeout means the operation did not happen. |
| Maximum payload sizes | JSON request bodies: 1 MB. File uploads: configured maximum (Section 23), independent of the JSON body limit since uploads use `multipart/form-data`. |
| Pagination guarantees | `page_size` never exceeds 100 (Section 12); `total_records` reflects the count at query time and is not guaranteed to remain accurate across subsequent pages if records are concurrently created or soft-deleted — a property of any paginated system over a live table, not specific to this API. |

---

## 27. Observability

**Structured logs.** Every request is logged with a consistent set of structured fields (per the ADD's logging philosophy): timestamp, `request_id`, authenticated user id, endpoint, status code, and duration. Logs are operational tooling, distinct from the immutable `audit_logs` table (DSD Section 6) — a log entry can be rotated or purged; an audit entry never is.

**Correlation IDs.** Every response includes `meta.request_id` (Section 9). If the caller supplies an `X-Request-Id` header (Section 8), that value is echoed back and used as the correlation id in server-side logs; otherwise the server generates one. This allows a single user-reported issue to be traced through logs without needing database access.

**Tracing.** Each request's correlation id ties together its Presentation-Layer call, its Application Service invocation, and its Repository Layer database call, giving a lightweight, log-based trace of a single request's path through the layers described in the ADD — without introducing a dedicated distributed-tracing system, which would be disproportionate for a single-process monolith.

**Metrics.** The latency figures in Section 25.2 and the rate limits in Section 15 are the two categories of metric this API is expected to expose (e.g., via Supabase's own dashboard and simple counters in the Scheduler's periodic jobs), rather than a dedicated metrics-collection service outside the fixed stack.

**Health endpoints.** A lightweight, unauthenticated `GET /api/v1/health` returns `{ "data": { "status": "ok" } }` with `200` when the process can reach its Supabase connection, and is intended for basic uptime checking only — it is not a substitute for the metrics described above and carries no business data.

**Audit correlation.** Because every mutating endpoint's transaction includes an `AuditLogEntry` write (Section 21) tagged with the same request's correlation id in its `metadata` field, an operational log entry and its corresponding permanent audit record can always be cross-referenced, giving a complete picture — operational and business — of any single write.

---

## 28. API Documentation Strategy

### 28.1 OpenAPI Mapping

This specification is designed to map mechanically onto an OpenAPI 3.x document through a fixed pipeline:

```
Endpoint (Section 19)
      │
      ▼
Pydantic v2 Model (src/models — e.g., RequestCreate, Request)
      │   model_json_schema()
      ▼
JSON Schema
      │   embedded as a `components.schemas` entry
      ▼
OpenAPI Schema (paths, methods, parameters, requestBody, responses
      all drawn directly from this document's Sections 18–22)
      │
      ▼
Swagger UI (renders the OpenAPI document for interactive exploration)
```

Each stage above is a direct, lossless transformation of the one before it: the Pydantic model is already the single source of truth for a resource's shape (per the ADD's Domain Layer), Pydantic v2 emits JSON Schema for any model without additional annotation work, and an OpenAPI document is JSON Schema plus the path/method/status-code metadata already fully specified in Section 19. No stage requires re-deriving information not already present earlier in the pipeline.

### 28.2 Swagger Generation

Should this API be exposed over an actual HTTP binding (Section 32), the OpenAPI document generated per Section 28.1 can be served directly through Swagger UI, giving interactive, always-current reference documentation with no duplication of the validation logic already defined once in `src/models`.

### 28.3 Future Automated Documentation

This document remains the authoritative, human-authored specification. A generated OpenAPI/Swagger artifact is a companion to this document, checked for consistency against it, not a replacement for the architectural reasoning recorded here (why REST was chosen, why a given field is immutable, why a given transaction boundary exists).

---

## 29. API Testing Strategy

| Test Category | Scope | Example |
|---|---|---|
| Unit tests | A single Application Service method, with repositories replaced by in-memory fakes (per the ADD's constructor-injection pattern) | `RequestService.submit_request` rejects an inactive `request_type` |
| Contract tests | A request/response pair against this document's schemas (Section 10) and status codes (Section 11), independent of business logic correctness | `POST /requests` with a missing `title` returns exactly the `422 VALIDATION_ERROR` shape specified in Section 11.1 |
| Integration tests | An endpoint exercised against a real (test-instance) Supabase database, verifying the full transaction described in Section 21 actually commits atomically | `POST /workflow-stages/{id}/approve` on the final stage leaves `Request.status = completed` and `WorkflowStage.status = approved` in the same commit |
| Authentication tests | Missing/expired/malformed token handling (Section 5) | A request with an expired JWT returns `401 AUTHENTICATION_REQUIRED` before any service method runs |
| Authorization tests | Role and ownership enforcement (Section 6), at both the Application Layer and RLS | An `employee` calling `POST /workflow-stages/{id}/approve` receives `403 PERMISSION_DENIED`; a direct RLS-level test additionally confirms the same call would be blocked even if the Application Layer's own check were bypassed |
| Optimistic locking tests | Concurrent update handling (DSD Section 3.9, Section 14.4) | Two simulated concurrent `approve` calls against the same `stage_id`: the first succeeds, the second receives `409 STAGE_ALREADY_DECIDED` |
| Validation tests | Every rule in Section 22, exercised at its boundary (e.g., exactly 200 vs. 201 characters for `title`) | `title` of length 201 returns `422 VALIDATION_ERROR`; length 200 succeeds |

Every test category above is implemented with `pytest`, per the fixed technology stack — no additional testing framework is introduced. Contract tests in particular are written against this document's Sections 9–11 directly, so that a change to the response shape described here is caught by a failing test before it reaches the Presentation Layer.

---

## 30. Sequence Diagrams

### 30.1 Request Submission

```
Presentation Layer        RequestService        WorkflowEngine       Repository Layer      PostgreSQL
       │                        │                     │                     │                  │
       │  submit_request(data)  │                     │                     │                  │
       ├───────────────────────▶│                     │                     │                  │
       │                        │  get_active_definition(request_type)      │                  │
       │                        ├────────────────────▶│                     │                  │
       │                        │                     │  fetch definition   │                  │
       │                        │                     ├────────────────────▶│                  │
       │                        │                     │                     │  SELECT ...      │
       │                        │                     │                     ├─────────────────▶│
       │                        │                     │◀────────────────────┤◀─────────────────┤
       │                        │◀────────────────────┤                     │                  │
       │                        │  BEGIN TRANSACTION                        │                  │
       │                        ├───────────────────────────────────────────┼─────────────────▶│
       │                        │  INSERT Request                          │                  │
       │                        ├───────────────────────────────────────────┼─────────────────▶│
       │                        │  INSERT WorkflowStage (order=1)          │                  │
       │                        ├───────────────────────────────────────────┼─────────────────▶│
       │                        │  UPDATE Request.current_stage_id          │                  │
       │                        ├───────────────────────────────────────────┼─────────────────▶│
       │                        │  INSERT AuditLogEntry                     │                  │
       │                        ├───────────────────────────────────────────┼─────────────────▶│
       │                        │  COMMIT                                   │                  │
       │                        ├───────────────────────────────────────────┼─────────────────▶│
       │                        │  NotificationService.notify(assignee)     │                  │
       │                        ├─────────────────▶ (out of band, same transaction's audit trail)
       │  201 Created (Request) │                     │                     │                  │
       │◀───────────────────────┤                     │                     │                  │
```

### 30.2 Approval Decision

```
Presentation Layer      ApprovalService       WorkflowEngine       Repository Layer      PostgreSQL
       │                      │                     │                     │                  │
       │  approve(stage_id,   │                     │                     │                  │
       │  expected_version)   │                     │                     │                  │
       ├─────────────────────▶│                     │                     │                  │
       │                      │  check assignee/role, status == pending   │                  │
       │                      ├────────────────────────────────────────────┼─────────────────▶│
       │                      │                     │                     │  SELECT stage    │
       │                      │◀───────────────────────────────────────────┼──────────────────┤
       │                      │  BEGIN TRANSACTION                        │                  │
       │                      ├───────────────────────────────────────────┼─────────────────▶│
       │                      │  UPDATE WorkflowStage SET status='approved'│                  │
       │                      │  WHERE id=stage_id AND version=expected    │                  │
       │                      ├───────────────────────────────────────────┼─────────────────▶│
       │                      │  0 rows affected? ──▶ ROLLBACK, 409        │                  │
       │                      │  1 row affected  ──▶ continue              │                  │
       │                      │  get_next_stage(request, current_order)   │                  │
       │                      ├────────────────────▶│                     │                  │
       │                      │◀────────────────────┤                     │                  │
       │                      │  INSERT next WorkflowStage OR              │                  │
       │                      │  UPDATE Request.status/completed_at        │                  │
       │                      ├───────────────────────────────────────────┼─────────────────▶│
       │                      │  UPDATE Request.current_stage_id           │                  │
       │                      ├───────────────────────────────────────────┼─────────────────▶│
       │                      │  INSERT AuditLogEntry                      │                  │
       │                      ├───────────────────────────────────────────┼─────────────────▶│
       │                      │  COMMIT                                    │                  │
       │                      ├───────────────────────────────────────────┼─────────────────▶│
       │                      │  NotificationService.notify(requester,     │                  │
       │                      │    next assignee if any)                   │                  │
       │  200 OK (stage,      │                     │                     │                  │
       │  request)            │                     │                     │                  │
       │◀─────────────────────┤                     │                     │                  │
```

---

## 31. Example End-to-End Workflow

The following trace shows a single two-stage `expense_reimbursement` request from submission to completion, tying together the endpoints, transactions, and diagrams above into one concrete example.

1. **Jane (employee)** calls `POST /api/v1/requests` with `request_type: expense_reimbursement`. Per Section 21.1, a `Request` (`status: pending`), its first `WorkflowStage` ("Manager Review", `status: pending`, `assigned_to`: her manager), and an `AuditLogEntry` (`REQUEST_CREATED`) are committed together. Her manager receives an `assignment` notification.
2. **Jane** calls `POST /api/v1/requests/{id}/attachments` to upload `receipt.pdf`. Per Section 23, the file is sanitized, MIME-sniffed, checksummed, written to Storage, and only then recorded as an `Attachment` row alongside a second `AuditLogEntry` (`ATTACHMENT_UPLOADED`).
3. **Her manager (approver)** calls `GET /api/v1/approvals/pending`, sees the request, and calls `GET /api/v1/requests/{id}/attachments` and `GET /api/v1/requests/{id}/comments` to review context.
4. **Her manager** calls `POST /api/v1/workflow-stages/{stage_id}/approve` with a `decision_note`. Per Section 21.4 and the sequence in Section 30.2: the "Manager Review" stage is marked `approved`; because a second stage ("Finance Review") exists in the active `WorkflowDefinition`, it is created (`status: pending`, assigned to the finance department queue); `Request.status` moves to `in_review` and `current_stage_id` advances; an `AuditLogEntry` (`STAGE_APPROVED`) is written. Jane receives a `decision` notification; the finance queue receives an `assignment` notification.
5. **A finance approver** calls `POST /api/v1/workflow-stages/{stage_id}/approve` on the second stage. Because no further stage exists in the definition, `Request.status` moves to `completed`, `completed_at` is set, `current_stage_id` is cleared, and a final `AuditLogEntry` (`STAGE_APPROVED`) is written in the same transaction. Jane receives a `completion` notification.
6. **Jane** calls `GET /api/v1/requests/{id}` (now `status: completed`), `GET /api/v1/requests/{id}/workflow/history` (both stages, both `approved`), and `GET /api/v1/requests/{id}/audit-log` (the complete, immutable four-entry trail: `REQUEST_CREATED`, `ATTACHMENT_UPLOADED`, and two `STAGE_APPROVED` entries), confirming the entire lifecycle is independently reconstructable from the audit trail alone, per Section 24.

---

## 32. Future Evolution

**GraphQL.** A GraphQL layer could be added as an alternative query interface over the same Application Services without altering them, resolving each field through the same repository calls already specified here.

**WebSockets.** Real-time notification delivery could be layered on top of the existing `NotificationService` without changing its interface, replacing polling of `GET /api/v1/notifications/unread-count` with a push of the same payload already defined in Section 10.6.

**Mobile clients.** Because this specification is already transport-agnostic in its data shapes and authentication model (Section 5), a native mobile client could consume the same contract with no changes to the Application Layer, whenever an actual network binding is introduced.

**Third-party integrations.** External systems (e.g., a future Slack or Teams integration, anticipated in the DSD's Future Database Evolution) would consume this same API surface — most directly Notifications and Requests — rather than requiring a separate integration-specific contract.

**API Gateway.** Should this API be exposed over a real network boundary, a gateway could front it for TLS termination or centralized rate limiting (Section 15) without requiring any change to the endpoint specifications in Section 19.

None of these evolutions require restructuring the Application, Domain, or Repository layers described in the ADD, and none require introducing technology outside the project's fixed stack today.

---

## 33. Glossary

**ADD** — Architecture Design Document; the source of truth for EAH's layered architecture and component responsibilities.

**Application Service** — A class in `src/services` (e.g., `RequestService`, `ApprovalService`) that orchestrates a use case by coordinating domain models, the Workflow Engine, and repositories.

**Approver** — A `user_role` value; a user permitted to decide approval stages assigned to them.

**Audit Log Entry** — An immutable, append-only row in `audit_logs`, recording a single state-changing action.

**Contract** — The formal specification of an endpoint's request/response shape and behavior, as defined in this document, independent of its current physical binding (Section 1.2).

**DSD** — Database Schema Design Document; the source of truth for table structure, constraints, RLS, and transactions.

**Idempotent** — An operation that produces the same end state whether performed once or multiple times (Section 14).

**Optimistic Locking** — A concurrency-control strategy using a `version` column to detect, rather than prevent, conflicting concurrent updates (DSD Section 3.9).

**Presentation Layer** — Originally the Streamlit-based UI code in `src/ui`; now the Next.js/React frontend in `frontend/`, the sole current consumer of the contract specified in this document.

**Repository Layer** — The `src/repositories` code that translates between domain models and Supabase's data representation; the only layer that issues database queries.

**RLS (Row-Level Security)** — PostgreSQL's mechanism for restricting row visibility/mutability per authenticated user, independent of application-level checks (DSD Section 9).

**Soft Delete** — Marking a row as removed via `deleted_at`/`deleted_by` rather than physically deleting it (DSD Section 3.10).

**SRS** — Software Requirements Specification; the source of truth for functional and non-functional requirements this system satisfies.

**Stage (Workflow Stage)** — A single approval step within a request's lifecycle, instantiated from a `WorkflowDefinition`'s JSON document.

**Version (concurrency)** — The integer column used for optimistic locking on a given row (not to be confused with the API's own `/v1` versioning, Section 7, or a `WorkflowDefinition`'s business-level `version` field, DSD Section 3.2).

**Workflow Definition** — A versioned, JSON-encoded document describing the ordered approval chain for a given request type (DSD Section 5).

**Workflow Engine** — The `src/workflows` component that resolves a request type's active definition and determines stage ordering and assignment.