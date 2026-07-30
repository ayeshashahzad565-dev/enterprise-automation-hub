import { format } from "date-fns";

import type { AuditAction, AuditEntry } from "@/types/audit";

const ACTION_LABELS: Record<AuditAction, string> = {
  REQUEST_CREATED: "Request created",
  REQUEST_WITHDRAWN: "Request withdrawn",
  STAGE_APPROVED: "Stage approved",
  STAGE_REJECTED: "Stage rejected",
  STAGE_ESCALATED: "Stage escalated",
  WORKFLOW_DEFINITION_ACTIVATED: "Workflow definition activated",
  COMMENT_CREATED: "Comment added",
  COMMENT_REMOVED: "Comment removed",
  ATTACHMENT_UPLOADED: "Attachment uploaded",
  ATTACHMENT_REMOVED: "Attachment removed",
  PROFILE_UPDATED: "Profile updated",
};

/** Per-action custom copy — matches the backend's metadata-snapshot-only shape (no generic diff viewer). */
export function ActivityTimeline({ entries }: { entries: AuditEntry[] }) {
  if (entries.length === 0) {
    return <p className="text-sm text-muted-foreground">No activity yet.</p>;
  }

  return (
    <ol className="space-y-4 border-l pl-4">
      {entries.map((entry, index) => (
        <li key={index} className="relative">
          <span className="absolute top-1.5 -left-[1.1rem] size-2 rounded-full bg-primary" />
          <p className="text-sm font-medium">{ACTION_LABELS[entry.action] ?? entry.action}</p>
          <p className="text-xs text-muted-foreground">
            {entry.actor_name ?? "System"} · {format(new Date(entry.created_at), "PPp")}
          </p>
        </li>
      ))}
    </ol>
  );
}
