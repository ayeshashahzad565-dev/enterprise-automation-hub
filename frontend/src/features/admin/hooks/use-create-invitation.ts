"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { adminKeys } from "@/features/admin/query-keys";
import { adminService } from "@/services/admin-service";
import type { CreateInvitationBody } from "@/types/admin";

export function useCreateInvitation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (body: CreateInvitationBody) => adminService.createInvitation(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: adminKeys.invitations() });
    },
  });
}
