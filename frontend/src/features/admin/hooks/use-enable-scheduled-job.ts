"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { adminKeys } from "@/features/admin/query-keys";
import { adminService } from "@/services/admin-service";

export function useEnableScheduledJob() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (name: string) => adminService.enableScheduledJob(name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: adminKeys.scheduledJobs() });
    },
  });
}
