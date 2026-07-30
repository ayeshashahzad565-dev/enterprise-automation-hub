"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { requestKeys } from "@/features/requests/query-keys";
import { requestService } from "@/services/request-service";
import type { RequestCreateInput } from "@/types/request";

export function useCreateRequest() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: RequestCreateInput) => requestService.create(input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: requestKeys.lists() });
    },
  });
}
