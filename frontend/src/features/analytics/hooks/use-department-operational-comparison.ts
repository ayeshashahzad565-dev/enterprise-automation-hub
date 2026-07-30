"use client";

import { useQueries } from "@tanstack/react-query";

import { operationalAnalyticsKeys } from "@/features/analytics/query-keys";
import { operationalAnalyticsService } from "@/services/operational-analytics-service";
import type { OperationalAnalyticsFilters } from "@/types/operational-analytics";

/** One query per compared department — mirrors ``useDepartmentComparison``'s
 * identical pattern for the base Analytics feature, applied to operational
 * (SLA/throughput/backlog) figures instead of raw request counts. */
export function useDepartmentOperationalComparison(
  departments: string[],
  filters: Pick<OperationalAnalyticsFilters, "created_after" | "created_before">,
) {
  return useQueries({
    queries: departments.map((department) => ({
      queryKey: operationalAnalyticsKeys.department(department, filters),
      queryFn: () => operationalAnalyticsService.getDepartmentAnalytics(department, filters),
      staleTime: 30_000,
    })),
  });
}
