"use client";

import { useQuery } from "@tanstack/react-query";

import { analyticsKeys } from "@/features/analytics/query-keys";
import { analyticsService } from "@/services/analytics-service";
import type { AnalyticsFilters } from "@/types/analytics";

export function useApprovalMetrics(filters: AnalyticsFilters) {
  return useQuery({
    queryKey: analyticsKeys.approvals(filters),
    queryFn: () => analyticsService.getApprovalMetrics(filters),
    staleTime: 30_000,
  });
}
