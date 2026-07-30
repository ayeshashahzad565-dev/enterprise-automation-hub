"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { notificationKeys } from "@/features/notifications/query-keys";
import { notificationService } from "@/services/notification-service";
import type { Notification } from "@/types/notification";

interface NotificationListPage {
  data: Notification[];
  pagination: { page: number; page_size: number; total_records: number; total_pages: number };
}

/** Optimistically removes the archived notification from every cached list, mirroring Requests' withdraw pattern. */
export function useArchiveNotification() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => notificationService.archive(id),
    onMutate: async (id: string) => {
      await queryClient.cancelQueries({ queryKey: notificationKeys.lists() });
      const previousLists = queryClient.getQueriesData<NotificationListPage>({
        queryKey: notificationKeys.lists(),
      });
      queryClient.setQueriesData<NotificationListPage | undefined>(
        { queryKey: notificationKeys.lists() },
        (old) => (old ? { ...old, data: old.data.filter((item) => item.id !== id) } : old),
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
