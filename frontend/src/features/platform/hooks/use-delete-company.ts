"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { platformKeys } from "@/features/platform/query-keys";
import { platformService } from "@/services/platform-service";

export function useDeleteCompany() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, expectedVersion }: { id: string; expectedVersion: number }) =>
      platformService.deleteCompany(id, expectedVersion),
    onSettled: (_data, _error, variables) => {
      queryClient.invalidateQueries({ queryKey: platformKeys.companies() });
      queryClient.invalidateQueries({ queryKey: platformKeys.company(variables.id) });
    },
  });
}
