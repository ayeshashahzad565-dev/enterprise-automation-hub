import {
  AlertTriangle,
  CheckCircle2,
  FileText,
  GitBranch,
  MessageSquare,
  Paperclip,
  Trash2,
  UserCog,
  XCircle,
  type LucideIcon,
} from "lucide-react";

import type { AuditAction } from "@/types/activity";

const ICONS: Record<AuditAction, LucideIcon> = {
  REQUEST_CREATED: FileText,
  REQUEST_WITHDRAWN: Trash2,
  STAGE_APPROVED: CheckCircle2,
  STAGE_REJECTED: XCircle,
  STAGE_ESCALATED: AlertTriangle,
  WORKFLOW_DEFINITION_ACTIVATED: GitBranch,
  COMMENT_CREATED: MessageSquare,
  COMMENT_REMOVED: Trash2,
  ATTACHMENT_UPLOADED: Paperclip,
  ATTACHMENT_REMOVED: Trash2,
  PROFILE_UPDATED: UserCog,
};

export function ActivityIcon({ action, className }: { action: AuditAction; className?: string }) {
  const Icon = ICONS[action];
  return <Icon className={className} aria-hidden />;
}
