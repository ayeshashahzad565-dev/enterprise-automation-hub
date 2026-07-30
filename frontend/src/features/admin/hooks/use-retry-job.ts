"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { adminKeys } from "@/features/admin/query-keys";
import { adminService } from "@/services/admin-service";

export function useRetryJob() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => adminService.retryJob(id),
    onSuccess: () => {
      // A retried job leaves the dead-letter queue and re-enters the
      // regular list as `queued`, and the dead-letter count in the stats
      // summary changes too — invalidate every job-scoped query at once
      // rather than enumerating list/dead-letter/stats individually.
      queryClient.invalidateQueries({ queryKey: adminKeys.jobs() });
    },
  });
}
