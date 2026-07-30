"use client";

import { useQuery } from "@tanstack/react-query";

import { operationalAnalyticsKeys } from "@/features/analytics/query-keys";
import { operationalAnalyticsService } from "@/services/operational-analytics-service";
import type { OperationalAnalyticsFilters } from "@/types/operational-analytics";

export function useBottlenecks(filters: OperationalAnalyticsFilters & { limit?: number }) {
  return useQuery({
    queryKey: operationalAnalyticsKeys.bottlenecks(filters),
    queryFn: () => operationalAnalyticsService.getBottlenecks(filters),
    staleTime: 30_000,
  });
}
