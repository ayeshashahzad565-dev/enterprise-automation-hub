"use client";

import { useQuery } from "@tanstack/react-query";

import { operationalAnalyticsKeys } from "@/features/analytics/query-keys";
import { operationalAnalyticsService } from "@/services/operational-analytics-service";
import type { OperationalAnalyticsFilters } from "@/types/operational-analytics";

export function useApprovalDelays(filters: OperationalAnalyticsFilters & { limit?: number }) {
  return useQuery({
    queryKey: operationalAnalyticsKeys.approvalDelays(filters),
    queryFn: () => operationalAnalyticsService.getApprovalDelays(filters),
    staleTime: 30_000,
  });
}
