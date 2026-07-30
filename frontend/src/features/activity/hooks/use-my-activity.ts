"use client";

import { useQuery } from "@tanstack/react-query";

import { activityKeys } from "@/features/activity/query-keys";
import { activityService } from "@/services/activity-service";
import type { ActivityListFilters } from "@/types/activity";

/** The caller's own activity — available to every role, self-scoped, no cross-user exposure. */
export function useMyActivity(filters: Omit<ActivityListFilters, "actor_id">) {
  return useQuery({
    queryKey: activityKeys.mine(filters),
    queryFn: () => activityService.getMyActivity(filters),
    staleTime: 60_000,
  });
}
