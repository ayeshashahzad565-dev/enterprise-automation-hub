"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { adminKeys } from "@/features/admin/query-keys";
import { adminService } from "@/services/admin-service";

export function useResendInvitation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => adminService.resendInvitation(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: adminKeys.invitations() });
    },
  });
}
