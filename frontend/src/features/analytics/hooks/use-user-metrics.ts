"use client";

import { useQuery } from "@tanstack/react-query";

import { analyticsKeys } from "@/features/analytics/query-keys";
import { analyticsService } from "@/services/analytics-service";

export function useUserMetrics(userId: string | undefined) {
  return useQuery({
    queryKey: analyticsKeys.user(userId ?? ""),
    queryFn: () => analyticsService.getUserMetrics(userId as string),
    enabled: Boolean(userId),
    staleTime: 30_000,
  });
}
