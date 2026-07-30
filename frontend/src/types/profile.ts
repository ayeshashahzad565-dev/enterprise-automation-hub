/**
 * Defined independently from the REST contract documented in
 * `docs/api_design.md` §10.1 ("Profile" resource schema) — not imported or
 * mirrored from the backend's Python domain model.
 */

export type UserRole = "employee" | "approver" | "admin";

export interface Profile {
  id: string;
  full_name: string;
  role: UserRole;
  department: string | null;
  /** The company (tenant) this profile belongs to — every profile has exactly one. */
  company_id: string;
  /** Platform-level administrator (can manage companies), orthogonal to `role`. */
  is_platform_admin: boolean;
  created_at: string;
  updated_at: string;
  version: number;
}
