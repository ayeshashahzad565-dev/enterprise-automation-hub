"use client";

import { useQuery } from "@tanstack/react-query";

import { analyticsKeys } from "@/features/analytics/query-keys";
import { analyticsService } from "@/services/analytics-service";
import type { AnalyticsFilters } from "@/types/analytics";

export function useExecutiveSummary(filters: Pick<AnalyticsFilters, "created_after" | "created_before">) {
  return useQuery({
    queryKey: analyticsKeys.executiveSummary(filters),
    queryFn: () => analyticsService.getExecutiveSummary(filters),
    staleTime: 60_000,
  });
}
