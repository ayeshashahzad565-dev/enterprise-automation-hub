/**
 * Frontend-owned types for the Platform Administration module
 * (`/api/v1/admin/*`) — defined independently of the backend's Pydantic
 * schemas, matching the convention every other `types/*.ts` file in this
 * project follows.
 */

import type { AuditLogEntry } from "@/types/activity";
import type { UserRole } from "@/types/profile";

export interface AdminUser {
  id: string;
  full_name: string;
  role: UserRole;
  department: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface UpdateAdminUserBody {
  expected_version: number;
  role?: UserRole;
  department?: string;
}

export interface RolePermissions {
  role: UserRole;
  permissions: string[];
}

export interface DepartmentMemberCounts {
  employee: number;
  approver: number;
  admin: number;
}

export interface DepartmentSummary {
  department: string;
  member_count: number;
  roles: DepartmentMemberCounts;
}

export interface DepartmentWorkload {
  department: string;
  member_count: number;
  workload: number;
  members: AdminUser[];
}

/** No settings field beyond this list exists on the backend — see
 * `app.api.schemas.admin.PlatformSettingsOut`'s own docstring for the
 * explicit allow-list this mirrors (no SMTP credentials, no raw
 * database/Supabase connection strings). */
export interface PlatformSettings {
  environment: string;
  default_escalation_hours: number;
  read_per_minute: number;
  write_per_minute: number;
  upload_per_minute: number;
  login_per_5_minutes: number;
  notification_poll_per_minute: number;
  log_level: string;
  smtp_enabled: boolean;
}

/** `workflow_definition_counts` is keyed by request_type; only the
 * request types this frontend already knows about (no cross-type "list
 * every definition" backend method exists — see the admin_dashboard
 * router's docstring). */
export interface AdminDashboard {
  total_users: number;
  department_count: number;
  pending_approvals_count: number;
  workflow_definition_counts: Record<string, number>;
  recent_activity: AuditLogEntry[];
}

/** Mirrors `app.models.enums.EffectiveInvitationStatus` — the computed,
 * caller-facing status the backend derives from the persisted status
 * plus `expires_at` (see `InvitationOut`'s own docstring; `expired` is
 * never a persisted value). */
export type InvitationStatus = "pending" | "expired" | "accepted" | "revoked";

/** Mirrors `app.api.schemas.admin_invitations.InvitationOut` exactly —
 * deliberately excludes `version`/`token_hash`, which that schema never
 * returns either. */
export interface Invitation {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  department: string | null;
  effective_status: InvitationStatus;
  invited_by: string;
  expires_at: string;
  accepted_at: string | null;
  revoked_at: string | null;
  accepted_profile_id: string | null;
  resend_count: number;
  created_at: string;
  updated_at: string;
}

/** Mirrors `app.api.schemas.admin_invitations.InvitationCreateBody`. */
export interface CreateInvitationBody {
  email: string;
  full_name: string;
  role: UserRole;
  department?: string;
}
