"use client";

import { useQuery } from "@tanstack/react-query";

import { adminKeys } from "@/features/admin/query-keys";
import { adminService } from "@/services/admin-service";

/** Scheduled jobs run on the order of minutes to hours, so a longer
 * interval than the job history/queue stats polling is enough to keep
 * run counts and next-run times reasonably fresh without over-polling. */
const AUTO_REFRESH_INTERVAL_MS = 20_000;

export function useScheduledJobs() {
  return useQuery({
    queryKey: adminKeys.scheduledJobs(),
    queryFn: () => adminService.listScheduledJobs(),
    staleTime: 10_000,
    refetchInterval: AUTO_REFRESH_INTERVAL_MS,
  });
}
