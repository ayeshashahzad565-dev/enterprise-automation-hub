"use client";

import { useQuery } from "@tanstack/react-query";

import { notificationKeys } from "@/features/notifications/query-keys";
import { notificationService } from "@/services/notification-service";

/**
 * The bell badge's count — the first query in this app to use
 * `refetchInterval` (every other feature relies on `staleTime` +
 * refetch-on-focus only). Justified here since it's a single cheap count
 * query, not a full list refetch, and the badge is the one surface that
 * should feel "live" without the user doing anything. 15s (4/min) stays
 * well within `RATE_LIMIT_NOTIFICATION_POLL_PER_MINUTE`'s 30/min budget;
 * `refetchOnWindowFocus` (TanStack Query's default, unmodified in
 * `createQueryClient`) additionally refreshes immediately whenever the
 * user tabs back in, rather than waiting out the interval.
 */
export function useUnreadCount() {
  return useQuery({
    queryKey: notificationKeys.unreadCount(),
    queryFn: () => notificationService.getUnreadCount(),
    staleTime: 10_000,
    refetchInterval: 15_000,
  });
}
