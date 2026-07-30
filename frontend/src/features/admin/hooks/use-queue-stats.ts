"use client";

import { useQuery } from "@tanstack/react-query";

import { adminKeys } from "@/features/admin/query-keys";
import { adminService } from "@/services/admin-service";

/** Short interval — this is the closest thing to a "live" queue depth
 * gauge on this page, so it refreshes noticeably faster than the job
 * history table itself. */
const AUTO_REFRESH_INTERVAL_MS = 10_000;

export function useQueueStats() {
  return useQuery({
    queryKey: adminKeys.jobsStats(),
    queryFn: () => adminService.getQueueStats(),
    staleTime: 5_000,
    refetchInterval: AUTO_REFRESH_INTERVAL_MS,
  });
}
