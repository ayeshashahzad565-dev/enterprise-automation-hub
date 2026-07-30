"use client";

import { useQuery } from "@tanstack/react-query";

import { platformKeys } from "@/features/platform/query-keys";
import { platformService } from "@/services/platform-service";

/** Health/dependency status is worth refreshing fairly often, similar to
 * `useQueueStats`, so an admin watching this page notices a recovered or
 * newly-degraded dependency without a manual refresh. */
const AUTO_REFRESH_INTERVAL_MS = 20_000;

export function usePlatformHealth() {
  return useQuery({
    queryKey: platformKeys.health(),
    queryFn: () => platformService.getHealth(),
    staleTime: 10_000,
    refetchInterval: AUTO_REFRESH_INTERVAL_MS,
  });
}
