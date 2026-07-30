"use client";

import { useQuery } from "@tanstack/react-query";

import { analyticsKeys } from "@/features/analytics/query-keys";
import { analyticsService } from "@/services/analytics-service";
import type { AnalyticsFilters, TimeGranularity } from "@/types/analytics";

export function useTrend(granularity: TimeGranularity, filters: Omit<AnalyticsFilters, "request_type"> & { request_type?: string }) {
  return useQuery({
    queryKey: analyticsKeys.trend(granularity, filters),
    queryFn: () => analyticsService.getTrend(granularity, filters),
    staleTime: 60_000,
  });
}
