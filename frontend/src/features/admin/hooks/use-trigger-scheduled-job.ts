"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { adminKeys } from "@/features/admin/query-keys";
import { adminService } from "@/services/admin-service";

export function useTriggerScheduledJob() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (name: string) => adminService.triggerScheduledJob(name),
    onSuccess: () => {
      // Triggering doesn't wait for the run to finish (the endpoint
      // returns 202 immediately) — invalidating here just picks up
      // `currently_running: true` a little sooner; the 20s poll on
      // `useScheduledJobs` is what eventually shows the finished outcome.
      queryClient.invalidateQueries({ queryKey: adminKeys.scheduledJobs() });
    },
  });
}
