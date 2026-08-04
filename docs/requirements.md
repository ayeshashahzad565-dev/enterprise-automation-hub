# Software Requirements Specification (SRS)
## Project: Enterprise Automation Hub (EAH)

**Document Version:** 1.2.0
**Date:** July 7, 2026
**Author:** Senior Software Architect
**Status:** Version 1.2 Approved

> **Superseded note:** This SRS was written against EAH's original baseline
> design (a Streamlit UI with Plotly charts, per the ADD of the time). The
> Presentation Layer has since been fully rebuilt as a FastAPI REST API
> (`app/`) with a separate Next.js 15 / React 19 frontend (`frontend/`).
> Functional requirements below remain the intended behavior; any mention of
> Streamlit, `st.session_state`, or Plotly describes the original
> implementation technology, not the shipped one. See `docs/deployment.md`
> and `docs/history/project_summary.md` for the current stack.

---

### 1. Executive Summary

The Enterprise Automation Hub (EAH) is a production-quality business workflow automation platform designed as a practical, high-caliber software engineering portfolio project. The application functions as a centralized internal hub where team members submit structural requests, managers review automated approval queues, and operations teams track service-level agreements (SLAs) through a dedicated data visualization engine.

Rather than deploying complex microservices or enterprise infrastructure, EAH is engineered using a pragmatic, single-developer tech stack: a Python 3.11 core engine, a Streamlit web interface, a Supabase (PostgreSQL) backend, and Pydantic data validation. The primary architectural objective is to demonstrate strict adherence to clean code patterns, domain separation, absolute data auditability, and precise schema validation within a realistic, maintainable system footprint.

---

### 2. Problem Statement

Small-to-medium businesses (SMBs) and corporate departments frequently track internal operational processes—such as procurement, equipment provisioning, and leave adjustments—via unstructured email chains and isolated spreadsheets. This approach introduces significant business friction:

**Process Blindness:** Approvers lose track of requests inside cluttered inboxes, resulting in unpredictable execution delays.

**Absence of a Ground Truth Ledger:** Compliance and internal management cannot verify when an operational step occurred or who authorized a specific expenditure.

**Fragile Data Integrity:** Hand-entered tracking files are prone to accidental modification, invalid formatting, and state inconsistencies.

**Lack of Performance Analytics:** Teams cannot easily quantify their process velocity, track common bottlenecks, or measure operational volume.

---

### 3. Project Objectives

The Enterprise Automation Hub establishes a production-grade blueprint for workflow management by meeting these engineering targets:

- **Unified Request Framework:** Consolidate multiple internal request archetypes into a standardized database structure using dynamic, JSON-driven field definitions.
- **Deterministic State Orchestration:** Eliminate broken lifecycles by executing all status updates through a centralized Python state engine.
- **Pydantic Serialization and Type Safety:** Enforce end-to-end data integrity from frontend inputs to relational database storage layers.
- **High Operational Visibility:** Deliver clear, responsive performance dashboards using interactive Plotly interfaces.
- **Developer Efficiency & Maintainability:** Build a highly organized monolithic structure utilizing clear domain design boundaries, ensuring it can be developed, tested, and maintained by a solo engineer.

---

### 4. User Roles and Permissions

The platform implements an application-level Role-Based Access Control (RBAC) matrix. Permissions are verified deterministically across all views, forms, and data execution pathways.

| Role | System String | Target User Definition | Permitted Application Capabilities |
| --- | --- | --- | --- |
| **Submitter** | `ROLE_SUBMITTER` | Standard internal employee or team member. | Create requests, view personal historical ledger, upload file attachments, append text comments to owned cases. |
| **Approver** | `ROLE_APPROVER` | Team leaders, department managers, or financial leads. | Access assigned review queues, execute Approve/Reject operations, view globally shared request history profiles. |
| **Administrator** | `ROLE_ADMIN` | IT operations or application developers. | Register and modify workflow JSON configurations, manage global user profile roles, and access system execution logs. |

---

### 5. Functional Requirements

#### 5.1 Authentication and Identity Management (AUTH)

- **FR-101:** The system MUST authenticate users through Supabase Auth utilizing standard email-and-password or passwordless magic link mechanisms.
- **FR-102:** The system MUST retrieve and store the user's explicit role authorization string within a secure Postgres profiles table, matching it to the application session state on load.
- **FR-103:** The platform MUST provide a user profile view showing the current authenticated user's name, email, role, and department designation.

#### 5.2 Workflow Configuration and Parsing (WFS)

- **FR-201:** The system MUST define workflows exclusively using a single flat JSON format configuration profile stored within a dedicated PostgreSQL table.
- **FR-202:** Each workflow type MUST be modeled in the JSON configuration profile as a basic flat array of sequential routing steps, explicitly mapping each step to an authorized target role string (e.g., `ROLE_APPROVER`) and a flat integer SLA hour limit.
- **FR-203:** The system MUST validate all database-loaded JSON configuration profiles at application runtime using a strict Pydantic parsing class to guarantee basic key presence and type safety before requests can be instantiated.

#### 5.3 Request Lifecycle and Data Mutation (REQ)

- **FR-301:** The system MUST generate an immutable, unique identifier (UUIDv4) for every submission immediately upon creation.
- **FR-302:** The application MUST enforce sequential lifecycle states: `DRAFT` --> `PENDING` --> `APPROVED` | `REJECTED` --> `FULFILLED`.
- **FR-303:** The submission interface MUST reject any request payload containing missing or structurally invalid parameters based on the associated Pydantic schema validator.
- **FR-304:** The application MUST support binary file attachments (e.g., PDF invoices, equipment quotes) capped at a maximum file size of 5MB, routing them to Supabase Storage.
- **FR-305:** The system MUST allow authenticated users to append plain-text comments to any request they are authorized to view.
- **FR-306:** Comments MUST be append-only and immutable; the system MUST NOT expose any user-facing controls or backend API functions to update, edit, or delete a comment once committed.
- **FR-307:** The database schema MUST strictly bind each comment row to the author's User UUID, the parent Request UUID, and a server-generated UTC timestamp.

#### 5.4 Unified Grid, Search, and Filtering (UI-GRID)

- **FR-401:** The system MUST render an interaction grid displaying historical request parameters, current ownership status, and creation timestamps.
- **FR-402:** The user interface MUST provide a text search input capable of filtering records across target tracking identifiers, titles, and submitter credentials.
- **FR-403:** The system MUST support dynamic data filtering by lifecycle status, workflow type, and date ranges without generating interface rendering crashes.
- **FR-404:** The system MUST render an explicit, vertical Activity Timeline on the request detail view layout.
- **FR-405:** The Activity Timeline MUST chronologically aggregate and display a unified historical ledger of all lifecycle status changes, text comment submissions, and file attachment uploads grouped by their server UTC timestamps.

#### 5.5 Notification and Dispatch Infrastructure (NOT)

- **FR-501:** The system MUST generate explicit in-app banner alerts or notification panel list items inside the Streamlit user view upon request assignments.
- **FR-502:** The platform MUST support outbound email dispatch notifications using Python's native `smtplib` library or an external transactional provider API (e.g., SendGrid) when state modifications occur.

#### 5.6 Scheduling Engine and SLA Tracker (SCH)

- **FR-601:** The system MUST utilize an active `APScheduler` background worker routine to check pending requests against target SLA thresholds defined in the JSON configuration profile.
- **FR-602:** The scheduling process MUST mark requests as "Overdue" in the database layer when the current system timestamp exceeds the calculated deadline.

#### 5.7 Event-Driven Audit Engine (AUD)

- **FR-701:** The system MUST record a row entry inside a centralized database audit table for every user modification, validation error, and approval change.
- **FR-702:** The system audit log model MUST capture: record tracking timestamp, acting User UUID, execution action name, field key target, original value string, and new input value string.

#### 5.8 KPI Dashboard and Analytics (ANA)

**FR-801:** The system MUST calculate and render the following precise operational KPIs within the executive analytics tab:
- **Mean Time to Resolution (MTTR):** The average duration computed from initial `PENDING` insertion to final terminal state (`APPROVED`, `REJECTED`, or `FULFILLED`).
- **Step-Level Velocity:** The average active duration requests spend sitting inside a specific role's review queue before being acted upon.
- **SLA Breach Volume:** A raw historical count of requests that have transitioned into an "Overdue" state, segmented cleanly by workflow type.
- **Department Performance Distribution:** A multi-bar visualization displaying submission volumes and active approval-to-rejection ratios sorted by individual corporate department strings.

**FR-802:** The dashboard charts MUST render dynamically using interactive Plotly web elements natively embedded inside the Streamlit presentation layer.

---

### 6. Non-Functional Requirements

#### 6.1 Maintainability, Code Standards, and Testing

- **NFR-001 (Domain-Driven Design):** The application code repository MUST separate clear domain boundaries into distinct subfolders, ensuring database querying logic is decoupled from frontend rendering layouts.
- **NFR-002 (Type Enforcement):** All core business logic routines, data transformers, and validation workflows MUST use explicit Python type-hint definitions.
- **NFR-003 (Automated Unit Testing):** Core validation schemas, routing rules, and state engine changes MUST maintain a minimum of 80% test coverage using the `pytest` framework.

#### 6.2 Data Reliability and Concurrency Bounds

- **NFR-004 (Relational Consistency):** All database mutations MUST utilize foreign key constraints and strict relational indexing to ensure records cannot reference non-existent request nodes.
- **NFR-005 (Transactional Safeguards):** State changes involving multiple operations (e.g., inserting an approval record and updating the parent request state) MUST wrap inside a standard PostgreSQL database transaction block.
- **NFR-006 (Target Production Footprint):** The database architecture and indexing system MUST cleanly support an operational scale of up to 100,000 request log lines and 50 concurrent active platform connections without performance drop-offs.

---

### 7. Core Business Workflows

The application processing sequence routes through localized Python logic blocks and explicit data validations before writing state to the backend database.

```
+--------------------------------------------------------+
|                      Streamlit UI                      |
| (Submitter / Approver / Admin Interface Interactions)  |
+--------------------------------------------------------+
                           |
                           v
+--------------------------------------------------------+
|                 Pydantic Parse Layer                   |
|   (Validates Form Inputs Against Strict JSON Profile)  |
+--------------------------------------------------------+
                           |
                           v
+--------------------------------------------------------+
|               PostgreSQL Data Transaction              |
| (Performs Safe Inserts & Creates Immutable Audit Row)  |
+--------------------------------------------------------+
                           |
            +--------------+--------------+
            |                             |
            v                             v
+-----------------------+     +-----------------------+
|  APScheduler Deamon   |     |   Activity Timeline   |
| (SLA Overdue Checks)  |     | (Chronological Log)   |
+-----------------------+     +-----------------------+

```

#### 7.1 Lifecycle of a Business Workflow Execution

1. **Ingestion Layer:** The authenticated `ROLE_SUBMITTER` fills out form inputs within the Streamlit UI and optionally drops a binary file target into the attachment upload component.
2. **Schema Verification:** The frontend layer aggregates user inputs and forwards the payload into a dedicated workflow Pydantic data model initialized from the JSON configuration profile. If validation checks catch formatting errors, the interface displays clean field errors and stops the operation.
3. **Database Insertion:** Once validated, the system uploads any attached file to Supabase Storage, receives a public URL reference, bundles this reference with the structured payload, and sends it to the PostgreSQL instance via a secure transaction block.
4. **Audit and Transition Routing:** The database automatically fires an audit log insertion alongside the primary record generation. The platform state core transitions the tracking record status string to `PENDING` and assigns ownership tokens to the corresponding manager group specified in the active JSON configuration step.
5. **Timeline and Notification Dispatch:** The runtime logs the user mutation, generating a fresh entry in the historical comment/attachment database arrays. The UI instantly updates the request's vertical Activity Timeline, while an automated background notification mail is queued for the target `ROLE_APPROVER`.
6. **Resolution Processing:** The `ROLE_APPROVER` reviews the data profile, the chronological Activity Timeline, and the attachment link on their approval dashboard, then selects Approve or Reject. The system updates the transaction, generates a permanent audit line item, marks the case resolved, and notifies the original submitter.

---

### 8. System Constraints

- **C-001 (Monolithic Runtime):** The application interface and background scheduling engine MUST run as a unified monolithic runtime, eliminating the need for independent worker infrastructure (e.g., Celery, Redis).
- **C-002 (Streamlit UI Flow):** Application interactive logic MUST conform to Streamlit's script-execution rendering loop. Any advanced data persistence across interactions must depend exclusively on Streamlit's internal `st.session_state` parameters.
- **C-003 (Backend Scope):** Database architecture definitions must be fully compatible with open-source PostgreSQL. Database mutations must use standard SQL or the official Supabase Python client SDK.

---

### 9. Assumptions

- **A-001:** The target hosting instance or local developer platform maintains consistent internet routing out to the remote Supabase database and external storage endpoints.
- **A-002:** The volume of files remains within the free tier thresholds of standard hosting systems, meaning individual attachments never exceed the designated 5MB application block limit.
- **A-003:** Administrative configuration workflows (e.g., registering entirely new corporate request types) are handled via raw JSON uploads on the administrator control page, rather than using an online interactive form constructor.

---

### 10. Security Requirements

- **SEC-001 (Secure Key Management):** The system MUST NOT include production credentials, secret connection tokens, or external API keys within the Git source repository. All operational secrets MUST be loaded at runtime from a localized, non-committed `.env` context file using `pydantic-settings`.
- **SEC-002 (Transport Security):** Every connection pathway traversing between the Streamlit user view, the Supabase service API, and external mail engines MUST operate over standard HTTPS and TLS 1.3 encryption.
- **SEC-003 (PostgreSQL Row-Level Security):** The database tier MUST employ strict Postgres Row-Level Security (RLS) configurations. This ensures a standard user with a `ROLE_SUBMITTER` profile is restricted from reading or mutating unauthorized data structures belonging to other system users.
- **SEC-004 (Safe SQL Parameterization):** The database querying wrapper MUST explicitly pass variables using parameterized inputs. This standard applies to the Supabase client library or direct SQL statements, preventing SQL Injection (SQLi) vulnerabilities.

---

### 11. Performance Requirements

- **PERF-001 (Local Interface Response):** The execution latency for state transformations, internal database updates, and view updates within the Streamlit page layout MUST complete within 400 milliseconds under standard connectivity.
- **PERF-002 (Data Parsing Efficiency):** The parsing engine must validate intricate request parameters against complex Pydantic validation objects in less than 20 milliseconds, avoiding UI stuttering during submission.
- **PERF-003 (Render Performance):** Plotly chart generation routines within the analytics page must aggregate historical performance logs and render responsive components in under 800 milliseconds for up to 10,000 rows.

---

### 12. MVP Scope (v1.0)

#### Included in MVP Scope

- User authentication views using Supabase Email/Password structures.
- Direct configuration parsing from standard PostgreSQL JSON profiles using dedicated Pydantic structures.
- Standard request review layout engine incorporating active filtering, global search bars, profile histories, and vertical chronological Activity Timelines.
- Native rich-text commenting modules bound directly to individual request IDs.
- File attachment uploads (up to 5MB) routed directly to Supabase Storage buckets.
- Core state transitions: `DRAFT`, `PENDING`, `APPROVED`, `REJECTED`.
- Single-threaded `APScheduler` background routines verifying basic SLA violations.
- Relational audit tracking records appended to a structured PostgreSQL log table.
- Extended KPI analytics panels featuring automated MTTR math, queue velocity tracking, and Plotly visualization distributions.

#### Explicitly Excluded from MVP Scope

- Multi-tenant structural configurations (e.g., managing independent organizational entities on a shared application model).
- Visual drop-in flow builders or graphical canvas node interfaces for defining workflows.
- Advanced parallel approval branches running split paths or consensus-based logic across separate business groups.
- Integrations with heavy legacy enterprise resource planning platforms (e.g., SAP, Oracle, Workday).

---

### 13. Future Roadmap

**Phase 2 (Integration Extensions):** Introduce webhook consumer routes to accept automated incoming trigger data from developer systems like GitHub Actions or Jira Core.

**Phase 3 (Interactive Communications):** Build interactive Slack/Teams communication channels using localized bot integrations, letting managers process pending queues within their primary chat application.

**Phase 4 (Advanced Workflow Logic):** Support sophisticated multi-branch conditional logic and sub-workflow loops within the custom JSON configuration tables.

---

### 14. Success Criteria

- **Code Reliability Metrics:** Achieving a clean passing state across all automated `pytest` test units while maintaining more than 80% coverage on core data engine files.

- **Successful Deployment Verification:** The complete application stack runs smoothly on standard virtual container instances (e.g., Render, Railway, or Streamlit Community Cloud) without database communication failures.

- **Failsafe Audit Compliance:** Execution logs confirm that every state transition, attachment write, comment append, and approval change generates a corresponding row within the PostgreSQL audit ledger.

- **Clean Performance Baselines:** The UI updates smoothly under active data parsing conditions, keeping the 90th percentile (P90) interface latency under 500 milliseconds during record search, comment submission, and filter operations.