"use client";

import { useQuery } from "@tanstack/react-query";

import { operationalAnalyticsKeys } from "@/features/analytics/query-keys";
import { operationalAnalyticsService } from "@/services/operational-analytics-service";
import type { OperationalAnalyticsFilters } from "@/types/operational-analytics";

export function useExecutiveKpis(filters: OperationalAnalyticsFilters) {
  return useQuery({
    queryKey: operationalAnalyticsKeys.executive(filters),
    queryFn: () => operationalAnalyticsService.getExecutiveKpis(filters),
    staleTime: 30_000,
  });
}
