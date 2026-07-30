"use client";

import { useQueries } from "@tanstack/react-query";

import { analyticsKeys } from "@/features/analytics/query-keys";
import { analyticsService } from "@/services/analytics-service";
import type { AnalyticsFilters } from "@/types/analytics";

/** One query per added workflow (request) type — mirrors `useDepartmentComparison` exactly. */
export function useWorkflowComparison(
  requestTypes: string[],
  filters: Omit<AnalyticsFilters, "request_type">,
) {
  return useQueries({
    queries: requestTypes.map((requestType) => ({
      queryKey: analyticsKeys.workflow(requestType, filters),
      queryFn: () => analyticsService.getWorkflowMetrics(requestType, filters),
      staleTime: 30_000,
    })),
  });
}
