import { apiClient } from "@/lib/api/client";
import type { ActivityListFilters, AuditLogEntry } from "@/types/activity";

function buildQuery(params: object): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

export const activityService = {
  /** Admin-only, organization-wide feed. See `app.api.routers.analytics.list_recent_activity`. */
  getOrganizationActivity: (filters: ActivityListFilters = {}) =>
    apiClient.getList<AuditLogEntry>(`/audit-logs${buildQuery(filters)}`),
  /** The caller's own activity, every role. See `app.api.routers.activity.list_my_activity`. */
  getMyActivity: (filters: Omit<ActivityListFilters, "actor_id"> = {}) =>
    apiClient.getList<AuditLogEntry>(`/activity/mine${buildQuery(filters)}`),
};
