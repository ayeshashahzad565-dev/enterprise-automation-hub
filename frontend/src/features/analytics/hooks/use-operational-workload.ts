"use client";

import { useQuery } from "@tanstack/react-query";

import { operationalAnalyticsKeys } from "@/features/analytics/query-keys";
import { operationalAnalyticsService } from "@/services/operational-analytics-service";

export function useOperationalWorkload(department?: string) {
  const filters = { department };
  return useQuery({
    queryKey: operationalAnalyticsKeys.workload(filters),
    queryFn: () => operationalAnalyticsService.getWorkloadReport(filters),
    staleTime: 30_000,
  });
}
