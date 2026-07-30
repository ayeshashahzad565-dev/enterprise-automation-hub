"use client";

import { useQuery } from "@tanstack/react-query";

import { activityKeys } from "@/features/activity/query-keys";
import { activityService } from "@/services/activity-service";
import type { ActivityListFilters } from "@/types/activity";

/** Admin-only, organization-wide feed. Moved here from Analytics' `use-recent-activity.ts` in Phase 5 — Activity now owns this concept; Analytics' Operational tab imports it from here. */
export function useOrganizationActivity(filters: ActivityListFilters) {
  return useQuery({
    queryKey: activityKeys.organization(filters),
    queryFn: () => activityService.getOrganizationActivity(filters),
    staleTime: 60_000,
  });
}
