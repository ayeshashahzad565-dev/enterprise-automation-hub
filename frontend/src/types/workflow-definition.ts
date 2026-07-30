/**
 * Frontend-owned types for the `/api/v1/workflow-definitions` resource —
 * defined independently of the backend's Pydantic schemas, matching the
 * convention every other `types/*.ts` file in this project follows.
 *
 * The backend's workflow definition is strictly a linear, ordered list of
 * stages — there is no parallel-approval, conditional-routing, entry/exit
 * condition, or per-stage notification concept anywhere in the backend
 * (confirmed by direct audit of `app/workflow` and `app/models/workflow.py`
 * before this phase was built), so none of those fields exist here either.
 */

import type { UserRole } from "@/types/workflow";

export type AssignmentStrategy = "specific_user" | "department_queue" | "requester_manager";

export interface StageDefinition {
  order: number;
  name: string;
  assignment_strategy: AssignmentStrategy;
  assigned_role: UserRole | null;
  department: string | null;
  assigned_user_id: string | null;
  escalation_hours: number;
}

export interface WorkflowDefinitionDocument {
  stages: StageDefinition[];
}

export interface WorkflowDefinition {
  id: string;
  request_type: string;
  version: number;
  definition: WorkflowDefinitionDocument;
  is_active: boolean;
  created_by: string;
  row_version: number;
  created_at: string;
}

export interface CreateWorkflowDefinitionBody {
  request_type: string;
  definition: WorkflowDefinitionDocument;
}

export interface UpdateWorkflowDefinitionBody {
  definition: WorkflowDefinitionDocument;
}

/**
 * Draft/Active/Archived is inferred client-side, not a stored backend
 * status: the `is_active=true` version is Active; among the rest,
 * versions numbered below it are Archived (superseded), versions
 * numbered above it are Draft (not yet published); if none is active,
 * every version is a Draft.
 */
export type InferredStatus = "active" | "draft" | "archived";

export function inferStatus(
  definition: WorkflowDefinition,
  activeVersion: number | null,
): InferredStatus {
  if (definition.is_active) return "active";
  if (activeVersion === null) return "draft";
  return definition.version < activeVersion ? "archived" : "draft";
}
