import { format } from "date-fns";
import { AlertTriangle, Check, Circle, X } from "lucide-react";

import { Caption } from "@/components/patterns/typography";
import { cn } from "@/lib/utils";
import type { WorkflowProgress, WorkflowStageDetail } from "@/types/workflow";

function StageIcon({ stage, isCurrent }: { stage: WorkflowStageDetail; isCurrent: boolean }) {
  if (stage.status === "approved") return <Check className="size-4" aria-hidden />;
  if (stage.status === "rejected") return <X className="size-4" aria-hidden />;
  return <Circle className={cn("size-4", isCurrent && "fill-current")} aria-hidden />;
}

export function WorkflowProgressStepper({ progress }: { progress: WorkflowProgress }) {
  return (
    <ol className="flex flex-col gap-4 sm:flex-row sm:flex-wrap sm:gap-6">
      {progress.stages.map((stage) => {
        const isCurrent =
          stage.stage_order === progress.current_stage_order && stage.status === "pending";
        const isDone = stage.status === "approved";
        const isRejected = stage.status === "rejected";
        return (
          <li key={stage.stage_id} className="flex min-w-40 flex-1 items-start gap-2">
            <span
              className={cn(
                "mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full border",
                isDone &&
                  "border-status-completed bg-status-completed text-status-completed-foreground",
                isRejected &&
                  "border-status-rejected bg-status-rejected text-status-rejected-foreground",
                isCurrent &&
                  "border-status-in-review bg-status-in-review text-status-in-review-foreground",
                !isDone && !isRejected && !isCurrent && "border-border text-muted-foreground",
              )}
            >
              <StageIcon stage={stage} isCurrent={isCurrent} />
            </span>
            <div className="space-y-0.5">
              <p className="text-sm font-medium">{stage.stage_name}</p>
              {stage.assigned_to_name && <Caption>{stage.assigned_to_name}</Caption>}
              {stage.decided_at && (
                <Caption>
                  {stage.status === "approved" ? "Approved" : "Rejected"}{" "}
                  {format(new Date(stage.decided_at), "PP")}
                </Caption>
              )}
              {stage.decision_note && <Caption className="italic">&ldquo;{stage.decision_note}&rdquo;</Caption>}
              {stage.is_escalated && (
                <span className="inline-flex items-center gap-1 text-xs text-amber-600 dark:text-amber-400">
                  <AlertTriangle className="size-3" aria-hidden /> Escalated
                </span>
              )}
            </div>
          </li>
        );
      })}
      {progress.upcoming_stages.map((stage) => (
        <li key={stage.stage_order} className="flex min-w-40 flex-1 items-start gap-2 opacity-60">
          <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full border border-border text-muted-foreground">
            <Circle className="size-4" aria-hidden />
          </span>
          <p className="text-sm font-medium">{stage.stage_name}</p>
        </li>
      ))}
    </ol>
  );
}
