"use client";

import { useQuery } from "@tanstack/react-query";

import { adminKeys } from "@/features/admin/query-keys";
import { adminService } from "@/services/admin-service";

const AUTO_REFRESH_INTERVAL_MS = 15_000;

export function useDeadLetterJobs({
  taskType,
  page = 1,
  pageSize = 20,
}: {
  taskType?: string;
  page?: number;
  pageSize?: number;
}) {
  return useQuery({
    queryKey: adminKeys.jobsDeadLetter({ taskType, page, pageSize }),
    queryFn: () => adminService.listDeadLetterJobs({ taskType, page, pageSize }),
    staleTime: 10_000,
    refetchInterval: AUTO_REFRESH_INTERVAL_MS,
  });
}
