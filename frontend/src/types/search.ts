/**
 * Frontend-owned types for enterprise-wide search (`/api/v1/search/*`),
 * defined independently of the backend's Pydantic schemas, matching the
 * convention every other `types/*.ts` file in this project follows.
 */

/** Mirrors `app.services.search_service.ENTITY_TYPES`. `"department"` and
 * `"user"` results are only ever returned to an admin — a non-admin's
 * search silently omits them rather than 403ing, so this union is not
 * itself a permission boundary. */
export type SearchEntityType =
  | "request"
  | "approval"
  | "workflow"
  | "user"
  | "comment"
  | "audit_entry"
  | "department"
  | "notification"
  | "attachment";

/** One row of a search result. Only the fields relevant to `entity_type`
 * are meaningfully populated — a "request" and a "user" are genuinely
 * different shapes converging into one list for display. `snippet` is
 * Markdown with the match `**bolded**`; render it through
 * `renderHighlightedSnippet` rather than as plain text. */
export interface SearchResult {
  entity_type: SearchEntityType;
  id: string;
  title: string;
  subtitle: string;
  snippet: string;
  score: number;
  created_at: string;
  request_id: string | null;
  stage_id: string | null;
  stage_name: string | null;
  request_type: string | null;
}

export interface SearchParams {
  q: string;
  entityTypes?: SearchEntityType[];
  page?: number;
  pageSize?: number;
}

/** A user's own named, reusable search — backend-persisted so it syncs
 * across devices (an explicit choice over the `localStorage`-only
 * `SavedViewsMenu` pattern used elsewhere in this app). */
export interface SavedFilter {
  id: string;
  user_id: string;
  name: string;
  query_text: string;
  entity_types: SearchEntityType[] | null;
  filters: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface CreateSavedFilterBody {
  name: string;
  query_text?: string;
  entity_types?: SearchEntityType[] | null;
  filters?: Record<string, unknown>;
}

/** One past search — also the data source for "recent searches"/search
 * suggestions, not just a history log. */
export interface SearchHistoryEntry {
  id: string;
  query_text: string;
  entity_types: SearchEntityType[] | null;
  result_count: number;
  created_at: string;
}
