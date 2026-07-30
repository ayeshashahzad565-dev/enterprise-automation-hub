/**
 * Frontend-owned types for the Activity Center (`/api/v1/audit-logs` and
 * `/api/v1/activity/mine`) — defined independently of the backend's
 * Pydantic schemas, matching the convention every other `types/*.ts` file
 * in this project follows.
 *
 * `AuditLogEntry` moved here from `types/analytics.ts` in Phase 5: the
 * Activity feature is now its own consumer of the audit log (previously
 * only Analytics' "Recent Activity" widget read it), and this type is
 * reused by both, not redefined.
 */

import type { AuditAction } from "@/types/audit";

export type { AuditAction };

export interface AuditLogEntry {
  id: string;
  actor_id: string | null;
  actor_name: string | null;
  request_id: string | null;
  action: AuditAction;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface ActivityListFilters {
  action?: AuditAction;
  actor_id?: string;
  created_after?: string;
  created_before?: string;
  page?: number;
  page_size?: number;
}
