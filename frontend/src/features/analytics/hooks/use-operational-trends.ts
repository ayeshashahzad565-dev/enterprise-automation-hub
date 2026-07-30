"use client";

import { useQuery } from "@tanstack/react-query";

import { operationalAnalyticsKeys } from "@/features/analytics/query-keys";
import { operationalAnalyticsService } from "@/services/operational-analytics-service";
import type { TimeGranularity } from "@/types/analytics";
import type { OperationalAnalyticsFilters } from "@/types/operational-analytics";

export function useOperationalTrends(
  granularity: TimeGranularity,
  filters: OperationalAnalyticsFilters,
) {
  return useQuery({
    queryKey: operationalAnalyticsKeys.trends(granularity, filters),
    queryFn: () => operationalAnalyticsService.getTrends(granularity, filters),
    staleTime: 60_000,
  });
}
