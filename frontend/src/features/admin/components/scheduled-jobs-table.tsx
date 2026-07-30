"use client";

import { formatDistanceToNow } from "date-fns";
import { Play } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { ScheduledJob } from "@/types/jobs";

/** `interval_seconds` is always a whole number of seconds on the wire;
 * rendered as the coarsest unit that divides it evenly so "every 1h"
 * reads better than "every 3600s". */
function formatInterval(seconds: number): string {
  if (seconds > 0 && seconds % 3600 === 0) return `every ${seconds / 3600}h`;
  if (seconds > 0 && seconds % 60 === 0) return `every ${seconds / 60}m`;
  return `every ${seconds}s`;
}

function OutcomeBadge({ job }: { job: ScheduledJob }) {
  if (job.currently_running) {
    return <Badge variant="status-in-review">Running</Badge>;
  }
  if (!job.last_finished_at) {
    return <Badge variant="secondary">Never run</Badge>;
  }
  if (job.last_error) {
    return (
      <Tooltip>
        <TooltipTrigger>
          <Badge variant="status-rejected">Failed</Badge>
        </TooltipTrigger>
        <TooltipContent>{job.last_error}</TooltipContent>
      </Tooltip>
    );
  }
  return <Badge variant="status-completed">Success</Badge>;
}

export function ScheduledJobsTable({
  jobs,
  onToggle,
  onTrigger,
  togglingName,
  triggeringName,
}: {
  jobs: ScheduledJob[];
  onToggle: (job: ScheduledJob, enabled: boolean) => void;
  onTrigger: (job: ScheduledJob) => void;
  togglingName: string | null;
  triggeringName: string | null;
}) {
  return (
    <div className="overflow-hidden rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Interval</TableHead>
            <TableHead>Enabled</TableHead>
            <TableHead>Next run</TableHead>
            <TableHead>Last outcome</TableHead>
            <TableHead>Runs</TableHead>
            <TableHead>
              <span className="sr-only">Trigger now</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {jobs.map((job) => (
            <TableRow key={job.name}>
              <TableCell className="font-medium">{job.name}</TableCell>
              <TableCell className="text-sm text-muted-foreground">
                {formatInterval(job.interval_seconds)}
              </TableCell>
              <TableCell>
                <Switch
                  checked={job.enabled}
                  disabled={togglingName === job.name}
                  onCheckedChange={(checked) => onToggle(job, checked)}
                  aria-label={`${job.enabled ? "Disable" : "Enable"} ${job.name}`}
                />
              </TableCell>
              <TableCell className="text-sm text-muted-foreground">
                {job.next_run_time
                  ? formatDistanceToNow(new Date(job.next_run_time), { addSuffix: true })
                  : "—"}
              </TableCell>
              <TableCell>
                <OutcomeBadge job={job} />
              </TableCell>
              <TableCell className="text-sm text-muted-foreground tabular-nums">
                {job.success_count}/{job.run_count}
                {job.failure_count > 0 && (
                  <span className="text-destructive"> ({job.failure_count} failed)</span>
                )}
              </TableCell>
              <TableCell>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={job.currently_running || triggeringName === job.name}
                  onClick={() => onTrigger(job)}
                >
                  <Play className="size-4" />
                  {triggeringName === job.name ? "Triggering…" : "Trigger now"}
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
