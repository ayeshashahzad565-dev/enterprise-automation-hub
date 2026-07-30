import {
  Activity,
  Building2,
  CheckSquare,
  FileText,
  GitBranch,
  MessageSquare,
  Paperclip,
  Bell,
  User,
  type LucideIcon,
} from "lucide-react";

import type { SearchEntityType } from "@/types/search";

const ENTITY_META: Record<SearchEntityType, { icon: LucideIcon; label: string }> = {
  request: { icon: FileText, label: "Request" },
  approval: { icon: CheckSquare, label: "Approval" },
  workflow: { icon: GitBranch, label: "Workflow" },
  user: { icon: User, label: "User" },
  comment: { icon: MessageSquare, label: "Comment" },
  audit_entry: { icon: Activity, label: "Audit entry" },
  department: { icon: Building2, label: "Department" },
  notification: { icon: Bell, label: "Notification" },
  attachment: { icon: Paperclip, label: "Attachment" },
};

export function getSearchEntityMeta(entityType: SearchEntityType): { icon: LucideIcon; label: string } {
  return ENTITY_META[entityType];
}

export function SearchResultIcon({ entityType }: { entityType: SearchEntityType }) {
  const { icon: Icon } = getSearchEntityMeta(entityType);
  return <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />;
}
