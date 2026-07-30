/**
 * Defined independently from the REST contract documented in the
 * backend's `docs/api_design.md` §10.2 ("Request" resource schema) — not
 * imported or mirrored from the backend's Python domain model, matching
 * the same convention `types/profile.ts` established in Phase 1.
 */

export type RequestStatus = "pending" | "in_review" | "approved" | "rejected" | "completed";

export interface Request {
  id: string;
  requester_id: string;
  workflow_definition_id: string;
  request_type: string;
  title: string;
  description: string | null;
  department: string | null;
  status: RequestStatus;
  current_stage_id: string | null;
  version: number;
  deleted_at: string | null;
  deleted_by: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface RequestCreateInput {
  request_type: string;
  title: string;
  description?: string | null;
  department?: string | null;
}

export interface RequestPatchInput {
  title?: string | null;
  description?: string | null;
  department?: string | null;
  expected_version: number;
}

export interface RequestListFilters {
  status?: RequestStatus;
  request_type?: string;
  department?: string;
  search?: string;
}
