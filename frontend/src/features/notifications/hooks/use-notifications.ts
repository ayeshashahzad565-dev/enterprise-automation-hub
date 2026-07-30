"use client";

import { useQuery } from "@tanstack/react-query";

import { notificationKeys } from "@/features/notifications/query-keys";
import { notificationService } from "@/services/notification-service";
import type { NotificationListFilters } from "@/types/notification";

export function useNotifications(filters: NotificationListFilters, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: notificationKeys.list(filters),
    queryFn: () => notificationService.list(filters),
    staleTime: 15_000,
    placeholderData: (previousData) => previousData,
    enabled: options?.enabled,
  });
}
