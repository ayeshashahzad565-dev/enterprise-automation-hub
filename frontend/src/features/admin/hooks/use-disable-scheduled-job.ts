"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { adminKeys } from "@/features/admin/query-keys";
import { adminService } from "@/services/admin-service";

export function useDisableScheduledJob() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (name: string) => adminService.disableScheduledJob(name),
    onSuccess: () => {
      // A disable response may return `data: null` (the job is no longer
      // "visible" once disabled, per the API's own contract) — invalidating
      // and refetching the list is what actually reflects that, rather than
      // trying to merge a null single-resource response into cache.
      queryClient.invalidateQueries({ queryKey: adminKeys.scheduledJobs() });
    },
  });
}
