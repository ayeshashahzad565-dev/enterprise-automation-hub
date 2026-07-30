/**
 * Frontend-owned types for the Platform Administration module
 * (`/api/v1/platform/*`) — defined independently of the backend's
 * Pydantic schemas, matching the convention every other `types/*.ts`
 * file in this project follows. Distinct from `types/admin.ts`
 * (`/api/v1/admin/*`, gated on `role === "admin"`): everything here is
 * gated on `Profile.is_platform_admin` instead, an orthogonal capability
 * — see that field's own doc comment in `types/profile.ts`.
 */

import type { TrendPoint } from "@/types/analytics";

export interface Company {
  id: string;
  name: string;
  slug: string;
  is_active: boolean;
  contact_email: string | null;
  notes: string | null;
  version: number;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  deleted_by: string | null;
  is_deleted: boolean;
}

export interface CreateCompanyBody {
  name: string;
}

/** Body for `PATCH /platform/companies/{id}` — setting `is_active: false`
 * suspends every user in the company on their next request; setting it
 * `true` reactivates. Suspending/deleting a platform admin's own company
 * is rejected server-side with a 422 (self-lockout guard). */
export interface UpdateCompanyBody {
  expected_version: number;
  name?: string;
  is_active?: boolean;
  contact_email?: string;
  notes?: string;
}

/** A company's license/plan information, plus computed, informational
 * fields (`seats_used`/`is_expired`) — nothing in the backend enforces
 * these; they exist purely for a platform admin's own reference. */
export interface CompanyLicense {
  company_id: string;
  plan_tier: string;
  seat_limit: number | null;
  expires_at: string | null;
  notes: string | null;
  seats_used: number;
  is_expired: boolean;
  updated_at: string;
}

/** Body for `PATCH /platform/companies/{id}/license` — at least one
 * field required (422 otherwise); works for both first-time creation
 * (when the company has no license yet) and updates. */
export interface CompanyLicenseUpdateBody {
  plan_tier?: string;
  seat_limit?: number | null;
  expires_at?: string | null;
  notes?: string;
}

export interface FeatureFlag {
  key: string;
  description: string;
  enabled: boolean;
  updated_at: string;
}

export interface CreateFeatureFlagBody {
  key: string;
  description: string;
  enabled?: boolean;
}

/** Body for `PATCH /platform/feature-flags/{key}` — at least one field required. */
export interface UpdateFeatureFlagBody {
  description?: string;
  enabled?: boolean;
}

export interface PlatformStats {
  total_tenants: number;
  active_tenants: number;
  total_users: number;
  total_requests: number;
  /** Daily request-creation counts over the trailing 30 days — same
   * `TrendPoint` shape `TrendChart`/analytics already consume, so no new
   * chart primitive is needed for this panel. */
  request_volume_trend: TrendPoint[];
  active_workflow_definitions: number;
  total_storage_bytes: number;
}

/** `redis`/`job_queue`/`dead_letter_by_queue` are only present when Redis
 * is configured on the backend instance — render an "inactive"/"not
 * configured" state when absent, the same convention
 * `QueueStatsPanel`/`/admin/jobs` already uses for its own Redis-optional
 * fields. */
export interface PlatformHealth {
  status: "ok" | "degraded";
  database: "ok" | "unreachable";
  scheduler_active: boolean;
  redis?: "ok" | "unreachable";
  job_queue?: "ok" | "unreachable";
  dead_letter_by_queue?: Record<string, number>;
}

/** `action` intentionally isn't narrowed to a fixed string-literal union
 * (unlike `types/audit.ts`'s `AuditAction`): this feed spans every action
 * code the whole system produces (ordinary request/approval events *and*
 * the new `COMPANY_*`/`FEATURE_FLAG_*` platform events), and new codes
 * may be added over time — a plain `string` with an unrecognized-value
 * fallback in the label/icon maps is more robust than an exhaustive union
 * that breaks the build every time the backend enum grows. */
export interface PlatformAuditEntry {
  id: string;
  actor_id: string | null;
  company_id: string | null;
  request_id: string | null;
  action: string;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface PlatformAuditLogFilters {
  company_id?: string;
  actor_id?: string;
  action?: string;
  created_after?: string;
  created_before?: string;
  page?: number;
  page_size?: number;
}
