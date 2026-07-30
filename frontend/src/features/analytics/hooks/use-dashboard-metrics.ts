"use client";

import { useQuery } from "@tanstack/react-query";

import { analyticsKeys } from "@/features/analytics/query-keys";
import { analyticsService } from "@/services/analytics-service";
import type { AnalyticsFilters } from "@/types/analytics";

export function useDashboardMetrics(filters: AnalyticsFilters) {
  return useQuery({
    queryKey: analyticsKeys.dashboard(filters),
    queryFn: () => analyticsService.getDashboardMetrics(filters),
    staleTime: 30_000,
  });
}
