"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { adminKeys } from "@/features/admin/query-keys";
import { adminService } from "@/services/admin-service";
import type { UpdateAdminUserBody } from "@/types/admin";

export function useUpdateAdminUser() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: UpdateAdminUserBody }) =>
      adminService.updateUser(id, body),
    onSettled: (_data, _error, variables) => {
      queryClient.invalidateQueries({ queryKey: adminKeys.all });
      queryClient.invalidateQueries({ queryKey: adminKeys.user(variables.id) });
    },
  });
}
