"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { requestKeys } from "@/features/requests/query-keys";
import { requestService } from "@/services/request-service";
import type { RequestPatchInput } from "@/types/request";

/**
 * Not optimistic, deliberately: an edit needs the server's authoritative
 * new `version` back before a second edit is safe under optimistic
 * concurrency — an optimistic update here risks a confusing spurious
 * `409 CONCURRENT_UPDATE` on the very next save.
 */
export function useUpdateRequest(id: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: RequestPatchInput) => requestService.update(id, input),
    onSuccess: (updated) => {
      queryClient.setQueryData(requestKeys.detail(id), updated);
      queryClient.invalidateQueries({ queryKey: requestKeys.lists() });
    },
  });
}
