"use client";

import { useQueries } from "@tanstack/react-query";

import { analyticsKeys } from "@/features/analytics/query-keys";
import { analyticsService } from "@/services/analytics-service";
import type { AnalyticsFilters } from "@/types/analytics";

/** One query per added department — the count varies at runtime, so this uses `useQueries` rather than a fixed hook call. */
export function useDepartmentComparison(
  departments: string[],
  filters: Pick<AnalyticsFilters, "created_after" | "created_before">,
) {
  return useQueries({
    queries: departments.map((department) => ({
      queryKey: analyticsKeys.department(department, filters),
      queryFn: () => analyticsService.getDepartmentMetrics(department, filters),
      staleTime: 30_000,
    })),
  });
}
