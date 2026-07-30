"use client";

import { useQuery } from "@tanstack/react-query";

import { analyticsKeys } from "@/features/analytics/query-keys";
import { analyticsService } from "@/services/analytics-service";

export function useWorkloadSummary(department?: string) {
  return useQuery({
    queryKey: analyticsKeys.workload(department),
    queryFn: () => analyticsService.getWorkloadSummary(department),
    staleTime: 60_000,
  });
}
