# Enterprise-Wide Search

Cross-entity, fuzzy, filterable search across Requests, Approvals, Workflow Definitions,
Users, Departments, Comments, Notifications, Attachments, and Audit entries — a global
command palette (`Cmd/Ctrl+K` or `/`) plus a dedicated results page (`/search`), backed by
one Application Service (`app.services.search_service.GlobalSearchService`) and one router
(`app.api.routers.search`, `/api/v1/search/*`).

## Entity coverage and authorization

Every entity type reuses the authorization already enforced by its own service/repository —
`GlobalSearchService` introduces no new visibility rule:

| Entity | Scoping | Notes |
|---|---|---|
| `request` | `RequestService.search_requests` | Role-scoped (own/assigned/all) |
| `approval` | `ApprovalService.list_pending_approvals` | Caller's own pending queue only |
| `workflow` | `WorkflowDefinitionService.search_definitions` | Non-admin sees active definitions only |
| `user` | `ProfileRepository.search_by_name` | Admin-only |
| `department` | Derived from `admin_shared.fetch_all_profiles`/`group_profiles_by_department` | Admin-only; no `departments` table exists — a department is a free-text `Profile.department` string, so its search result `id` is a deterministic `uuid5` of the department name, not a real row id |
| `comment` | `CommentRepository.search`, scoped to the caller's visible request ids | |
| `audit_entry` | `AuditRepository.search`, scoped to the caller's visible request ids | Request-scoped only — distinct from the platform-wide, cross-tenant audit log at `/api/v1/platform/audit-log` |
| `notification` | `NotificationRepository.search_for_recipient` | Always scoped to the caller's own `user_id` |
| `attachment` | `AttachmentRepository.search`, scoped to the caller's visible request ids | |

## Indexing: trigram + full-text, not one or the other

Migration `0018_search_indexes` adds two complementary techniques:

1. **Trigram GIN indexes** (`pg_trgm`) on every short, single-field, name/label column already
   filtered with `ILIKE '%term%'` (`requests.title`/`description`, `workflow_definitions.request_type`,
   `profiles.full_name`, `notifications.message`, `attachments.file_name`, `audit_logs.action`,
   `comments.body`). Postgres can use a trigram GIN index for a leading-wildcard `ILIKE`, unlike a
   plain btree index — this required **no query-code changes** for those columns, just the index.
2. **Generated `tsvector` columns + GIN indexes** on `requests` (title weight `A`, description
   weight `B`) and `comments` (body) — the two entities with real prose bodies — enabling genuine
   stemmed, multi-word full-text ranking (`@@ websearch_to_tsquery`) that substring `ILIKE` alone
   can never provide (e.g. a query for "run" also matches a description containing "running").
   `RequestRepository.search_requests`/`CommentRepository.search` OR the `tsvector` match together
   with the existing `ILIKE` substring match in one indexed query, so both an instant partial-word
   typeahead match and a stemmed whole-word match are returned together.

## Pagination is over a bounded candidate window

`GlobalSearchService.search` fetches up to `MAX_PAGE_SIZE` (100) results per entity type,
merges and sorts them by fuzzy-match score, then slices the requested page from that merged
list. This is a deliberate, disclosed bound — the same "bounded candidate set" convention this
service already used for approval search before this feature — not a live, unbounded count
across an entire table. In practice this means `total_records` (and therefore the last page
number) reflects up to 900 candidate rows (100 per entity type × 9 types), not every row in
the database that would technically match.

## Saved filters and search history

Both are backend-persisted (`saved_filters`, `search_history` — migration `0019_saved_search`),
per-user and per-company, RLS-protected — an explicit choice over the `localStorage`-only
`SavedViewsMenu` pattern used elsewhere in this app, so a saved search or recent-search list
syncs across devices.

- A saved filter (`POST /search/saved-filters`) stores a name, the query text, an optional
  entity-type restriction, and an arbitrary `filters` JSON payload (opaque to the backend —
  interpreted by whichever frontend wrote it).
- Search history is append-only (`search()` records one entry per call, best-effort — a failed
  history write never breaks the search response itself) and unbounded, mirroring `audit_logs`/
  `jobs`'s own "no retention job in this pass" precedent. `list_recent_searches` de-duplicates
  by query text in Python (fetching a wider window and trimming), since PostgREST has no
  `DISTINCT ON`.

## Endpoints

| Method | Path | |
|---|---|---|
| `GET` | `/search?q=&entity_types=&page=&page_size=` | Cross-entity search |
| `GET` | `/search/saved-filters` | List the caller's saved filters |
| `POST` | `/search/saved-filters` | Save a new filter |
| `DELETE` | `/search/saved-filters/{id}` | Delete a saved filter (owner-only) |
| `GET` | `/search/history` | List the caller's recent searches |
| `DELETE` | `/search/history` | Clear the caller's search history |

`GET /search` has its own, higher rate-limit budget (`search_per_minute`, default 120/min,
`enforce_search_rate_limit`) on top of the general per-route limit, since both the command
palette and the dedicated search page issue one request per debounced keystroke — a
materially higher request rate than an ordinary read endpoint.

## Frontend

- **Command palette** (`Cmd/Ctrl+K` or `/`, `components/patterns/command-palette.tsx`):
  static navigation commands plus a live, grouped-by-entity-type search (top 5 per type),
  with a trailing "View all results" link to `/search?q=…`.
- **`/search`** (`app/(app)/search/page.tsx`): the full experience — debounced input, an
  entity-type filter panel (admin-only types hidden for a non-admin), grouped and highlighted
  results, pagination, a saved-filters menu (save/apply/delete), and recent searches (shown
  when the query is empty, doubling as search suggestions).
- Highlighted snippets are Markdown (`**match**`) from the backend, rendered as `<mark>` spans
  via `features/search/lib/render-highlighted-snippet.tsx`.
- Keyboard: `Cmd/Ctrl+K` and `/` both open the palette; arrow-key navigation in the palette
  comes free from `cmdk`; the dedicated page's result list supports Up/Down/Enter via a small,
  page-local handler.
