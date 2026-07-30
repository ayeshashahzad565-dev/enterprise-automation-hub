"use client";

import { getCoreRowModel, useReactTable } from "@tanstack/react-table";
import { AlertTriangle, ListChecks } from "lucide-react";
import { useState } from "react";

import { ConfirmDialog } from "@/components/patterns/confirm-dialog";
import { DataTable } from "@/components/patterns/data-table/data-table";
import { DataTablePagination } from "@/components/patterns/data-table/data-table-pagination";
import { DataTableSkeleton } from "@/components/patterns/data-table/data-table-skeleton";
import { DataTableToolbar } from "@/components/patterns/data-table/data-table-toolbar";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { PageHeader } from "@/components/patterns/page-header";
import { SectionHeading } from "@/components/patterns/typography";
import { Card, CardContent } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { buildJobColumns } from "@/features/admin/components/job-columns";
import { JobDetailPanel } from "@/features/admin/components/job-detail-panel";
import { QueueStatsPanel } from "@/features/admin/components/queue-stats-panel";
import { ScheduledJobsTable } from "@/features/admin/components/scheduled-jobs-table";
import { useAdminJobs } from "@/features/admin/hooks/use-admin-jobs";
import { useDeadLetterJobs } from "@/features/admin/hooks/use-dead-letter-jobs";
import { useDisableScheduledJob } from "@/features/admin/hooks/use-disable-scheduled-job";
import { useEnableScheduledJob } from "@/features/admin/hooks/use-enable-scheduled-job";
import { useQueueStats } from "@/features/admin/hooks/use-queue-stats";
import { useRetryJob } from "@/features/admin/hooks/use-retry-job";
import { useScheduledJobs } from "@/features/admin/hooks/use-scheduled-jobs";
import { useTriggerScheduledJob } from "@/features/admin/hooks/use-trigger-scheduled-job";
import { notifyError, notifySuccess } from "@/lib/toast";
import type { Job, JobPriority, JobStatus, ScheduledJob } from "@/types/jobs";

const STATUS_OPTIONS: ReadonlyArray<{ value: JobStatus; label: string }> = [
  { value: "queued", label: "Queued" },
  { value: "running", label: "Running" },
  { value: "retrying", label: "Retrying" },
  { value: "succeeded", label: "Succeeded" },
  { value: "dead_lettered", label: "Dead-lettered" },
];

const PRIORITY_OPTIONS: ReadonlyArray<{ value: JobPriority; label: string }> = [
  { value: "high", label: "High" },
  { value: "normal", label: "Normal" },
  { value: "low", label: "Low" },
];

// `queue_name` is a free-text string on the wire, not a closed enum — these
// are just the queue names known in the reference deployment, offered as a
// convenience filter; anything else is still reachable via the task search.
const QUEUE_OPTIONS: ReadonlyArray<{ value: string; label: string }> = [
  { value: "default", label: "default" },
  { value: "escalation", label: "escalation" },
];

const JOB_HISTORY_COLUMN_COUNT = 7;
const DEAD_LETTER_COLUMN_COUNT = 8;

function QueueStatsSkeleton() {
  return (
    <div className="grid gap-3 md:grid-cols-3">
      {Array.from({ length: 3 }).map((_, index) => (
        <Card key={index} size="sm">
          <CardContent className="space-y-2">
            <Skeleton className="h-4 w-28" />
            <Skeleton className="h-16 w-full" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function ScheduledJobsSkeleton() {
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="space-y-2 p-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-8 w-full" />
        ))}
      </div>
    </div>
  );
}

export default function AdminJobsPage() {
  // Job history filters/pagination
  const [taskType, setTaskType] = useState("");
  const [status, setStatus] = useState<JobStatus | undefined>(undefined);
  const [queueName, setQueueName] = useState<string | undefined>(undefined);
  const [priority, setPriority] = useState<JobPriority | undefined>(undefined);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  // Dead-letter filters/pagination (independent of the job-history table)
  const [dlTaskType, setDlTaskType] = useState("");
  const [dlPage, setDlPage] = useState(1);
  const [dlPageSize, setDlPageSize] = useState(20);

  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
  const [retryTarget, setRetryTarget] = useState<Job | null>(null);
  const [retryingId, setRetryingId] = useState<string | null>(null);
  const [togglingName, setTogglingName] = useState<string | null>(null);
  const [triggeringName, setTriggeringName] = useState<string | null>(null);

  const statsQuery = useQueueStats();
  const scheduledJobsQuery = useScheduledJobs();
  const jobsQuery = useAdminJobs({
    status,
    taskType: taskType.trim() || undefined,
    queueName,
    priority,
    page,
    pageSize,
  });
  const deadLetterQuery = useDeadLetterJobs({
    taskType: dlTaskType.trim() || undefined,
    page: dlPage,
    pageSize: dlPageSize,
  });

  const enableMutation = useEnableScheduledJob();
  const disableMutation = useDisableScheduledJob();
  const triggerMutation = useTriggerScheduledJob();
  const retryMutation = useRetryJob();

  const jobs = jobsQuery.data?.data ?? [];
  const deadLetterJobs = deadLetterQuery.data?.data ?? [];

  async function handleToggle(job: ScheduledJob, enabled: boolean) {
    setTogglingName(job.name);
    try {
      if (enabled) {
        await enableMutation.mutateAsync(job.name);
        notifySuccess(`${job.name} enabled.`);
      } else {
        await disableMutation.mutateAsync(job.name);
        notifySuccess(`${job.name} disabled.`);
      }
    } catch (error) {
      notifyError(error, "Couldn't update this scheduled job.");
    } finally {
      setTogglingName(null);
    }
  }

  async function handleTrigger(job: ScheduledJob) {
    setTriggeringName(job.name);
    try {
      await triggerMutation.mutateAsync(job.name);
      notifySuccess(`${job.name} triggered — it'll run in the background.`);
    } catch (error) {
      notifyError(error, "Couldn't trigger this scheduled job.");
    } finally {
      setTriggeringName(null);
    }
  }

  async function handleRetryConfirm() {
    if (!retryTarget) return;
    setRetryingId(retryTarget.id);
    try {
      await retryMutation.mutateAsync(retryTarget.id);
      notifySuccess(`${retryTarget.task_type} requeued.`);
    } catch (error) {
      notifyError(error, "Couldn't retry this job.");
    } finally {
      setRetryingId(null);
      setRetryTarget(null);
    }
  }

  const historyColumns = buildJobColumns();
  const historyTable = useReactTable({
    data: jobs,
    columns: historyColumns,
    getRowId: (row) => row.id,
    getCoreRowModel: getCoreRowModel(),
  });

  const deadLetterColumns = buildJobColumns({
    onRetry: (job) => setRetryTarget(job),
    retryingId,
  });
  const deadLetterTable = useReactTable({
    data: deadLetterJobs,
    columns: deadLetterColumns,
    getRowId: (row) => row.id,
    getCoreRowModel: getCoreRowModel(),
  });

  const hasHistoryFilter = Boolean(taskType || status || queueName || priority);
  const hasDeadLetterFilter = Boolean(dlTaskType);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Jobs"
        description="Monitor the background job queue, scheduled tasks, and dead-lettered jobs."
      />

      {statsQuery.isLoading ? (
        <QueueStatsSkeleton />
      ) : statsQuery.isError || !statsQuery.data ? (
        <ErrorState message="Couldn't load queue stats." onRetry={() => statsQuery.refetch()} />
      ) : (
        <QueueStatsPanel stats={statsQuery.data} />
      )}

      <div className="space-y-2">
        <SectionHeading>Scheduled jobs</SectionHeading>
        {scheduledJobsQuery.isLoading ? (
          <ScheduledJobsSkeleton />
        ) : scheduledJobsQuery.isError || !scheduledJobsQuery.data ? (
          <ErrorState
            message="Couldn't load scheduled jobs."
            onRetry={() => scheduledJobsQuery.refetch()}
          />
        ) : scheduledJobsQuery.data.length === 0 ? (
          <EmptyState
            icon={ListChecks}
            title="No scheduled jobs"
            description="No scheduler is active on this backend instance."
          />
        ) : (
          <ScheduledJobsTable
            jobs={scheduledJobsQuery.data}
            onToggle={handleToggle}
            onTrigger={handleTrigger}
            togglingName={togglingName}
            triggeringName={triggeringName}
          />
        )}
      </div>

      <div className="space-y-2">
        <SectionHeading>Job history</SectionHeading>
        <DataTableToolbar
          table={historyTable}
          searchValue={taskType}
          onSearchChange={(value) => {
            setTaskType(value);
            setPage(1);
          }}
          searchPlaceholder="Search job history by task type..."
          filters={
            <div className="flex flex-wrap items-center gap-2">
              <Select
                value={status ?? "all"}
                onValueChange={(value) => {
                  setStatus(value === "all" ? undefined : (value as JobStatus));
                  setPage(1);
                }}
              >
                <SelectTrigger size="sm" className="w-36">
                  <SelectValue placeholder="Status" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All statuses</SelectItem>
                  {STATUS_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select
                value={queueName ?? "all"}
                onValueChange={(value) => {
                  setQueueName(!value || value === "all" ? undefined : value);
                  setPage(1);
                }}
              >
                <SelectTrigger size="sm" className="w-32">
                  <SelectValue placeholder="Queue" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All queues</SelectItem>
                  {QUEUE_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select
                value={priority ?? "all"}
                onValueChange={(value) => {
                  setPriority(value === "all" ? undefined : (value as JobPriority));
                  setPage(1);
                }}
              >
                <SelectTrigger size="sm" className="w-32">
                  <SelectValue placeholder="Priority" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All priorities</SelectItem>
                  {PRIORITY_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          }
        />

        {jobsQuery.isLoading ? (
          <DataTableSkeleton columnCount={JOB_HISTORY_COLUMN_COUNT} />
        ) : jobsQuery.isError ? (
          <ErrorState message="Couldn't load jobs." onRetry={() => jobsQuery.refetch()} />
        ) : jobs.length === 0 ? (
          <EmptyState
            icon={ListChecks}
            title={hasHistoryFilter ? "No matching jobs" : "No jobs yet"}
            description={
              hasHistoryFilter
                ? "Try a different search term or filter."
                : "Jobs enqueued by the app will show up here."
            }
          />
        ) : (
          <>
            <DataTable table={historyTable} onRowClick={setSelectedJob} />
            <DataTablePagination
              page={jobsQuery.data?.pagination.page ?? 1}
              pageSize={jobsQuery.data?.pagination.page_size ?? pageSize}
              totalRecords={jobsQuery.data?.pagination.total_records ?? 0}
              totalPages={jobsQuery.data?.pagination.total_pages ?? 1}
              onPageChange={setPage}
              onPageSizeChange={(size) => {
                setPageSize(size);
                setPage(1);
              }}
            />
          </>
        )}
      </div>

      <div className="space-y-2">
        <SectionHeading>Dead-letter queue</SectionHeading>
        <DataTableToolbar
          table={deadLetterTable}
          searchValue={dlTaskType}
          onSearchChange={(value) => {
            setDlTaskType(value);
            setDlPage(1);
          }}
          searchPlaceholder="Search dead-letter jobs by task type..."
        />

        {deadLetterQuery.isLoading ? (
          <DataTableSkeleton columnCount={DEAD_LETTER_COLUMN_COUNT} />
        ) : deadLetterQuery.isError ? (
          <ErrorState
            message="Couldn't load dead-lettered jobs."
            onRetry={() => deadLetterQuery.refetch()}
          />
        ) : deadLetterJobs.length === 0 ? (
          <EmptyState
            icon={AlertTriangle}
            title={hasDeadLetterFilter ? "No matching dead-lettered jobs" : "No dead-lettered jobs"}
            description={
              hasDeadLetterFilter
                ? "Try a different search term."
                : "Jobs that exhaust their retry attempts show up here."
            }
          />
        ) : (
          <>
            <DataTable table={deadLetterTable} onRowClick={setSelectedJob} />
            <DataTablePagination
              page={deadLetterQuery.data?.pagination.page ?? 1}
              pageSize={deadLetterQuery.data?.pagination.page_size ?? dlPageSize}
              totalRecords={deadLetterQuery.data?.pagination.total_records ?? 0}
              totalPages={deadLetterQuery.data?.pagination.total_pages ?? 1}
              onPageChange={setDlPage}
              onPageSizeChange={(size) => {
                setDlPageSize(size);
                setDlPage(1);
              }}
            />
          </>
        )}
      </div>

      <JobDetailPanel
        job={selectedJob}
        open={selectedJob !== null}
        onOpenChange={(open) => !open && setSelectedJob(null)}
      />

      <ConfirmDialog
        open={Boolean(retryTarget)}
        onOpenChange={(open) => !open && setRetryTarget(null)}
        title="Retry this job?"
        description={`${retryTarget?.task_type ?? "This job"} will be requeued with a fresh attempt count.`}
        confirmLabel="Retry"
        destructive={false}
        isConfirming={retryMutation.isPending}
        onConfirm={handleRetryConfirm}
      />
    </div>
  );
}
