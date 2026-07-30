export type AuditAction =
  | "REQUEST_CREATED"
  | "REQUEST_WITHDRAWN"
  | "STAGE_APPROVED"
  | "STAGE_REJECTED"
  | "STAGE_ESCALATED"
  | "WORKFLOW_DEFINITION_ACTIVATED"
  | "COMMENT_CREATED"
  | "COMMENT_REMOVED"
  | "ATTACHMENT_UPLOADED"
  | "ATTACHMENT_REMOVED"
  | "PROFILE_UPDATED";

export interface AuditEntry {
  action: AuditAction;
  actor_name: string | null;
  created_at: string;
  metadata: Record<string, unknown> | null;
}
