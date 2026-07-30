"use client";

import { useQuery } from "@tanstack/react-query";

import { adminKeys } from "@/features/admin/query-keys";
import { adminService } from "@/services/admin-service";
import type { JobPriority, JobStatus } from "@/types/jobs";

/** Jobs move through queued -> running -> succeeded/dead_lettered on the
 * order of seconds, not the minutes an invitation's lifecycle spans, so
 * this polls noticeably faster than `useAdminInvitations`'s 45s. Uses
 * TanStack Query's own `refetchInterval` (no hand-rolled polling loop);
 * `refetchIntervalInBackground` is left at its default `false`, so
 * polling pauses once the tab loses focus. */
const AUTO_REFRESH_INTERVAL_MS = 15_000;

export function useAdminJobs({
  status,
  taskType,
  queueName,
  priority,
  page = 1,
  pageSize = 20,
}: {
  status?: JobStatus;
  taskType?: string;
  queueName?: string;
  priority?: JobPriority;
  page?: number;
  pageSize?: number;
}) {
  return useQuery({
    queryKey: adminKeys.jobsList({ status, taskType, queueName, priority, page, pageSize }),
    queryFn: () => adminService.listJobs({ status, taskType, queueName, priority, page, pageSize }),
    staleTime: 10_000,
    refetchInterval: AUTO_REFRESH_INTERVAL_MS,
  });
}
