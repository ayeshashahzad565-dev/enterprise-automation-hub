/**
 * Frontend-owned types for the `/api/v1/approvals*` resource — defined
 * independently of the backend's Pydantic schemas, matching the
 * convention every other `types/*.ts` file in this project follows.
 */

import type { RequestStatus } from "@/types/request";
import type { StageStatus, UserRole } from "@/types/workflow";

/** One row of the approval inbox: a pending stage merged with its owning request's summary. */
export interface ApprovalInboxItem {
  stage_id: string;
  stage_version: number;
  stage_order: number;
  stage_name: string;
  stage_status: StageStatus;
  assigned_role: UserRole | null;
  stage_created_at: string;
  request_id: string;
  request_title: string;
  request_type: string;
  department: string | null;
  requester_id: string;
  request_status: RequestStatus;
}

export interface DecisionInput {
  expected_version: number;
  decision_note?: string | null;
}

export interface ApprovalOutcomeStage {
  id: string;
  request_id: string;
  stage_order: number;
  stage_name: string;
  assigned_role: UserRole | null;
  assigned_to: string | null;
  status: StageStatus;
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  version: number;
  created_at: string;
}

export interface ApprovalOutcome {
  stage: ApprovalOutcomeStage;
  request_status: RequestStatus;
  current_stage_id: string | null;
}

export interface BulkDecisionItem {
  stage_id: string;
  expected_version: number;
  decision_note?: string | null;
}

export interface BulkDecisionResultItem {
  stage_id: string;
  success: boolean;
  error_code: string | null;
  error_message: string | null;
}

export interface BulkDecisionResult {
  results: BulkDecisionResultItem[];
}

export interface ApprovalEligibility {
  eligible: boolean;
  stage_id: string | null;
  expected_version: number | null;
}
