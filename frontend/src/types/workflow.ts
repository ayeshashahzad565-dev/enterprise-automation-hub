/** Frontend-owned types mirroring the backend's workflow-progress read model. */

export type StageStatus = "pending" | "approved" | "rejected" | "skipped";

export type UserRole = "employee" | "approver" | "admin";

export interface WorkflowStageDetail {
  stage_id: string;
  stage_order: number;
  stage_name: string;
  assigned_to_name: string | null;
  assigned_role: UserRole | null;
  status: StageStatus;
  created_at: string;
  decided_at: string | null;
  decided_by_name: string | null;
  decision_note: string | null;
  is_escalated: boolean;
}

export interface UpcomingStage {
  stage_order: number;
  stage_name: string;
}

export interface WorkflowProgress {
  stages: WorkflowStageDetail[];
  upcoming_stages: UpcomingStage[];
  current_stage_order: number;
  total_stages: number;
}
