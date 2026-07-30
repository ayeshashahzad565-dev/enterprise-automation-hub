"use client";

import { DefinitionList, DefinitionRow } from "@/components/patterns/definition-list";
import { JobStatusBadge } from "@/components/patterns/status-badge";
import { SubHeading } from "@/components/patterns/typography";
import { Badge } from "@/components/ui/badge";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import type { Job } from "@/types/jobs";

function formatTimestamp(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "—";
}

/** Row-detail drawer for a single job — same `Sheet`-based pattern as
 * `DepartmentDetailPanel`, except the full `Job` is already in hand from
 * the row the admin clicked (no extra fetch-by-id round trip needed). */
export function JobDetailPanel({
  job,
  open,
  onOpenChange,
}: {
  job: Job | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="flex w-full flex-col gap-4 overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>{job?.task_type ?? "Job"}</SheetTitle>
        </SheetHeader>

        {job && (
          <div className="space-y-4 px-4 pb-4">
            <div className="flex items-center gap-2">
              <JobStatusBadge status={job.status} />
              <Badge variant="outline" className="capitalize">
                {job.priority} priority
              </Badge>
            </div>

            <DefinitionList>
              <DefinitionRow label="Job ID">
                <span className="font-mono text-xs">{job.id}</span>
              </DefinitionRow>
              <DefinitionRow label="Queue">{job.queue_name}</DefinitionRow>
              <DefinitionRow label="Attempts">
                {job.attempts}/{job.max_attempts}
              </DefinitionRow>
              <DefinitionRow label="Created">{formatTimestamp(job.created_at)}</DefinitionRow>
              <DefinitionRow label="Scheduled for">
                {formatTimestamp(job.scheduled_for)}
              </DefinitionRow>
              <DefinitionRow label="Started">{formatTimestamp(job.started_at)}</DefinitionRow>
              <DefinitionRow label="Finished">{formatTimestamp(job.finished_at)}</DefinitionRow>
              <DefinitionRow label="Locked by">{job.locked_by ?? "—"}</DefinitionRow>
              <DefinitionRow label="Request ID">
                <span className="font-mono text-xs">{job.request_id ?? "—"}</span>
              </DefinitionRow>
              <DefinitionRow label="Actor ID">
                <span className="font-mono text-xs">{job.actor_id ?? "—"}</span>
              </DefinitionRow>
            </DefinitionList>

            {job.last_error && (
              <div className="space-y-1">
                <SubHeading>Last error</SubHeading>
                <p className="rounded-md bg-destructive/10 p-2 text-sm text-destructive">
                  {job.last_error}
                </p>
              </div>
            )}

            {job.error_history.length > 0 && (
              <div className="space-y-1">
                <SubHeading>Error history</SubHeading>
                <ul className="space-y-2">
                  {job.error_history.map((entry, index) => (
                    <li key={index} className="rounded-md border p-2 text-xs">
                      <p className="font-medium text-muted-foreground">
                        Attempt {entry.attempt} · {formatTimestamp(entry.at)}
                      </p>
                      <p className="mt-1 text-destructive">{entry.error}</p>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="space-y-1">
              <SubHeading>Payload</SubHeading>
              <pre className="max-h-80 overflow-auto rounded-md bg-muted p-3 text-xs">
                {JSON.stringify(job.payload, null, 2)}
              </pre>
            </div>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
