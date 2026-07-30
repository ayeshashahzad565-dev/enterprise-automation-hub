import type { SearchResult } from "@/types/search";
import { ROUTES } from "@/utils/constants";

/**
 * Where clicking a search result should navigate. `null` for a result
 * with no dedicated detail page in this app (e.g. a "user"/"department"
 * result — there is no user or department detail page) — the caller
 * should render those as non-clickable info rows.
 */
export function getSearchResultHref(result: SearchResult): string | null {
  switch (result.entity_type) {
    case "approval":
      return result.stage_id ? ROUTES.approval(result.stage_id) : null;
    case "workflow":
      return ROUTES.workflows;
    case "user":
      return ROUTES.adminUsers;
    case "department":
      return ROUTES.adminDepartments;
    case "request":
    case "comment":
    case "audit_entry":
    case "attachment":
    case "notification":
      return result.request_id ? ROUTES.request(result.request_id) : null;
    default:
      return null;
  }
}
