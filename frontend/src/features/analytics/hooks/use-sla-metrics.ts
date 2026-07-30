"use client";

import { useQuery } from "@tanstack/react-query";

import { operationalAnalyticsKeys } from "@/features/analytics/query-keys";
import { operationalAnalyticsService } from "@/services/operational-analytics-service";
import type { OperationalAnalyticsFilters } from "@/types/operational-analytics";

export function useSlaMetrics(filters: OperationalAnalyticsFilters & { sla_hours?: number }) {
  return useQuery({
    queryKey: operationalAnalyticsKeys.sla(filters),
    queryFn: () => operationalAnalyticsService.getSlaMetrics(filters),
    staleTime: 30_000,
  });
}
