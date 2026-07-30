"use client";

import { useQuery } from "@tanstack/react-query";

import { platformKeys } from "@/features/platform/query-keys";
import { platformService } from "@/services/platform-service";

export function useFeatureFlags() {
  return useQuery({
    queryKey: platformKeys.featureFlags(),
    queryFn: () => platformService.listFeatureFlags(),
    staleTime: 15_000,
  });
}
