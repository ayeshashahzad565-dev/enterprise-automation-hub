"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { notificationKeys } from "@/features/notifications/query-keys";
import { notificationService } from "@/services/notification-service";
import type { Notification } from "@/types/notification";

interface NotificationListPage {
  data: Notification[];
  pagination: { page: number; page_size: number; total_records: number; total_pages: number };
}

/**
 * Optimistically patches `is_read`/`read_at` in place (not filtered out —
 * a read notification stays visible until the user archives it). No
 * toast: marking a single notification read is a frequent, low-stakes
 * micro-action, and toasting every one would itself be the "notification
 * fatigue" this feature is meant to avoid.
 */
export function useMarkRead() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => notificationService.markRead(id),
    onMutate: async (id: string) => {
      await queryClient.cancelQueries({ queryKey: notificationKeys.lists() });
      const previousLists = queryClient.getQueriesData<NotificationListPage>({
        queryKey: notificationKeys.lists(),
      });
      queryClient.setQueriesData<NotificationListPage | undefined>(
        { queryKey: notificationKeys.lists() },
        (old) =>
          old
            ? {
                ...old,
                data: old.data.map((item) =>
                  item.id === id ? { ...item, is_read: true, read_at: new Date().toISOString() } : item,
                ),
              }
            : old,
      );
      return { previousLists };
    },
    onError: (_err, _id, context) => {
      context?.previousLists?.forEach(([key, data]) => {
        queryClient.setQueryData(key, data);
      });
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: notificationKeys.lists() });
      queryClient.invalidateQueries({ queryKey: notificationKeys.unreadCount() });
    },
  });
}
