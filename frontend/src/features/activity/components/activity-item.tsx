"use client";

import Link from "next/link";

import { ActivityIcon } from "@/features/activity/components/activity-icon";
import { formatRelativeTime } from "@/lib/format-relative-time";
import type { AuditAction, AuditLogEntry } from "@/types/activity";
import { ROUTES } from "@/utils/constants";

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

/** Shared row renderer for both the Organization and My Activity feeds. */
export function ActivityItem({
  entry,
  onActorClick,
}: {
  entry: AuditLogEntry;
  /** Org tab only: clicking the actor's name filters the feed to just them (no user-directory endpoint exists, so this captures the id from an already-displayed row). */
  onActorClick?: (actorId: string) => void;
}) {
  return (
    <div className="flex items-start gap-3 rounded-md px-3 py-2 text-sm">
      <ActivityIcon action={entry.action} className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
      <div className="min-w-0 flex-1 space-y-0.5">
        <p className="font-medium">
          {entry.request_id ? (
            <Link href={ROUTES.request(entry.request_id)} className="hover:underline">
              {ACTION_LABELS[entry.action] ?? entry.action}
            </Link>
          ) : (
            (ACTION_LABELS[entry.action] ?? entry.action)
          )}
        </p>
        <p className="text-xs text-muted-foreground">
          {entry.actor_id && onActorClick ? (
            <button type="button" className="hover:underline" onClick={() => onActorClick(entry.actor_id!)}>
              {entry.actor_name ?? "System"}
            </button>
          ) : (
            (entry.actor_name ?? "System")
          )}
          {" · "}
          {formatRelativeTime(entry.created_at)}
        </p>
      </div>
    </div>
  );
}
