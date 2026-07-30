import {
  AlertTriangle,
  Ban,
  Building2,
  CheckCircle2,
  Flag,
  GitBranch,
  Mail,
  MessageSquare,
  Paperclip,
  PlayCircle,
  Power,
  PowerOff,
  RotateCw,
  Settings,
  ShieldCheck,
  Trash2,
  UserCog,
  XCircle,
  type LucideIcon,
} from "lucide-react";

import type { AuditAction } from "@/types/activity";

/** Label/icon for every action code the whole system produces — this
 * feed (`GET /platform/audit-log`) is cross-tenant and spans ordinary
 * request/approval events *and* the new company/feature-flag platform
 * events, unlike the per-request Activity Center's narrower
 * `ACTION_LABELS` in `activity-item.tsx`. Keyed loosely (not
 * `Record<AuditAction, ...>`) with a raw-code fallback in
 * `getAuditActionMeta`, so an action code this map hasn't been updated
 * for yet still renders instead of crashing. */
const AUDIT_ACTION_META: Partial<Record<AuditAction | string, { label: string; icon: LucideIcon }>> = {
  REQUEST_CREATED: { label: "Request created", icon: Mail },
  REQUEST_WITHDRAWN: { label: "Request withdrawn", icon: Trash2 },
  STAGE_APPROVED: { label: "Stage approved", icon: CheckCircle2 },
  STAGE_REJECTED: { label: "Stage rejected", icon: XCircle },
  STAGE_ESCALATED: { label: "Stage escalated", icon: AlertTriangle },
  WORKFLOW_DEFINITION_ACTIVATED: { label: "Workflow definition activated", icon: GitBranch },
  COMMENT_CREATED: { label: "Comment added", icon: MessageSquare },
  COMMENT_REMOVED: { label: "Comment removed", icon: Trash2 },
  ATTACHMENT_UPLOADED: { label: "Attachment uploaded", icon: Paperclip },
  ATTACHMENT_REMOVED: { label: "Attachment removed", icon: Trash2 },
  PROFILE_UPDATED: { label: "Profile updated", icon: UserCog },
  INVITATION_CREATED: { label: "Invitation sent", icon: Mail },
  INVITATION_RESENT: { label: "Invitation resent", icon: RotateCw },
  INVITATION_REVOKED: { label: "Invitation revoked", icon: Ban },
  INVITATION_ACCEPTED: { label: "Invitation accepted", icon: CheckCircle2 },
  JOB_RETRIED: { label: "Job retried", icon: RotateCw },
  SCHEDULED_JOB_ENABLED: { label: "Scheduled job enabled", icon: Power },
  SCHEDULED_JOB_DISABLED: { label: "Scheduled job disabled", icon: PowerOff },
  SCHEDULED_JOB_TRIGGERED: { label: "Scheduled job triggered", icon: PlayCircle },
  COMPANY_CREATED: { label: "Company created", icon: Building2 },
  COMPANY_SUSPENDED: { label: "Company suspended", icon: PowerOff },
  COMPANY_REACTIVATED: { label: "Company reactivated", icon: Power },
  COMPANY_DELETED: { label: "Company deleted", icon: Trash2 },
  COMPANY_RESTORED: { label: "Company restored", icon: RotateCw },
  COMPANY_SETTINGS_UPDATED: { label: "Company settings updated", icon: Settings },
  COMPANY_LICENSE_UPDATED: { label: "Company license updated", icon: ShieldCheck },
  FEATURE_FLAG_UPDATED: { label: "Feature flag updated", icon: Flag },
};

export function getAuditActionMeta(action: string): { label: string; icon: LucideIcon } {
  return AUDIT_ACTION_META[action] ?? { label: action, icon: Settings };
}
