"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { notificationKeys } from "@/features/notifications/query-keys";
import { notificationService } from "@/services/notification-service";
import type { NotificationPreference, NotificationPreferenceUpdate } from "@/types/notification";

interface UpdatePreferenceInput {
  notificationType: string;
  body: NotificationPreferenceUpdate;
}

/** Optimistically toggles the switch immediately; rolls back on failure. */
export function useUpdateNotificationPreference() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ notificationType, body }: UpdatePreferenceInput) =>
      notificationService.updatePreference(notificationType, body),
    onMutate: async ({ notificationType, body }) => {
      await queryClient.cancelQueries({ queryKey: notificationKeys.preferences() });
      const previous = queryClient.getQueryData<NotificationPreference[]>(
        notificationKeys.preferences(),
      );
      queryClient.setQueryData<NotificationPreference[] | undefined>(
        notificationKeys.preferences(),
        (old) =>
          old?.map((preference) =>
            preference.notification_type === notificationType
              ? { ...preference, ...body }
              : preference,
          ),
      );
      return { previous };
    },
    onError: (_err, _variables, context) => {
      if (context?.previous) {
        queryClient.setQueryData(notificationKeys.preferences(), context.previous);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: notificationKeys.preferences() });
    },
  });
}
