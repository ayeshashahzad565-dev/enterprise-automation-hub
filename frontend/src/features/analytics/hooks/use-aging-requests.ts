"use client";

import { useQuery } from "@tanstack/react-query";

import { analyticsKeys } from "@/features/analytics/query-keys";
import { analyticsService } from "@/services/analytics-service";

export function useAgingRequests(params: { older_than_hours?: number; page?: number; page_size?: number }) {
  return useQuery({
    queryKey: analyticsKeys.agingRequests(params),
    queryFn: () => analyticsService.getAgingRequests(params),
    staleTime: 30_000,
  });
}
