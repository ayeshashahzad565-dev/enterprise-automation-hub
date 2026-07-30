"use client";

import type { ColumnDef } from "@tanstack/react-table";
import { formatDistanceToNow } from "date-fns";
import { RotateCw } from "lucide-react";

import { JobStatusBadge } from "@/components/patterns/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { Job } from "@/types/jobs";

export interface JobRowActions {
  onRetry?: (job: Job) => void;
  retryingId?: string | null;
}

/** Shared between the job-history table and the dead-letter table — the
 * only difference is whether `onRetry` is supplied, which adds a trailing
 * "Retry" column (dead-letter jobs are always retry-eligible, so unlike
 * `buildInvitationColumns` there's no per-row eligibility check needed). */
export function buildJobColumns(actions: JobRowActions = {}): ColumnDef<Job>[] {
  const columns: ColumnDef<Job>[] = [
    {
      accessorKey: "task_type",
      header: "Task",
      cell: ({ row }) => <span className="font-medium">{row.original.task_type}</span>,
    },
    {
      accessorKey: "queue_name",
      header: "Queue",
      cell: ({ row }) => (
        <span className="text-sm text-muted-foreground">{row.original.queue_name}</span>
      ),
    },
    {
      accessorKey: "priority",
      header: "Priority",
      cell: ({ row }) => (
        <Badge variant="outline" className="capitalize">
          {row.original.priority}
        </Badge>
      ),
    },
    {
      accessorKey: "status",
      header: "Status",
      cell: ({ row }) => <JobStatusBadge status={row.original.status} />,
    },
    {
      id: "attempts",
      header: "Attempts",
      cell: ({ row }) => (
        <span className="text-sm text-muted-foreground tabular-nums">
          {row.original.attempts}/{row.original.max_attempts}
        </span>
      ),
    },
    {
      accessorKey: "created_at",
      header: "Created",
      cell: ({ row }) => (
        <span className="text-sm text-muted-foreground">
          {formatDistanceToNow(new Date(row.original.created_at), { addSuffix: true })}
        </span>
      ),
    },
    {
      accessorKey: "finished_at",
      header: "Finished",
      cell: ({ row }) => (
        <span className="text-sm text-muted-foreground">
          {row.original.finished_at
            ? formatDistanceToNow(new Date(row.original.finished_at), { addSuffix: true })
            : "—"}
        </span>
      ),
    },
  ];

  if (actions.onRetry) {
    const onRetry = actions.onRetry;
    columns.push({
      id: "actions",
      header: () => <span className="sr-only">Quick actions</span>,
      cell: ({ row }) => {
        const job = row.original;
        const isRetrying = actions.retryingId === job.id;
        return (
          <Button variant="outline" size="sm" disabled={isRetrying} onClick={() => onRetry(job)}>
            <RotateCw className="size-4" /> {isRetrying ? "Retrying…" : "Retry"}
          </Button>
        );
      },
      enableSorting: false,
      enableHiding: false,
    });
  }

  return columns;
}
