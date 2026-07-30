"use client";

import { useQuery } from "@tanstack/react-query";

import { platformKeys } from "@/features/platform/query-keys";
import { platformService } from "@/services/platform-service";

export function usePlatformStats() {
  return useQuery({
    queryKey: platformKeys.stats(),
    queryFn: () => platformService.getStats(),
    staleTime: 30_000,
  });
}
