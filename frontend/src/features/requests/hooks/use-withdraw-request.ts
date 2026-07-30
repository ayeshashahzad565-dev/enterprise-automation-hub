"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { requestKeys } from "@/features/requests/query-keys";
import { requestService } from "@/services/request-service";
import type { Request } from "@/types/request";

interface WithdrawInput {
  id: string;
  expectedVersion: number;
}

interface RequestListPage {
  data: Request[];
  pagination: { page: number; page_size: number; total_records: number; total_pages: number };
}

/** Optimistically removes the request from every cached list immediately. */
export function useWithdrawRequest() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, expectedVersion }: WithdrawInput) =>
      requestService.withdraw(id, expectedVersion),
    onMutate: async ({ id }) => {
      await queryClient.cancelQueries({ queryKey: requestKeys.lists() });
      const previousLists = queryClient.getQueriesData<RequestListPage>({
        queryKey: requestKeys.lists(),
      });
      queryClient.setQueriesData<RequestListPage | undefined>(
        { queryKey: requestKeys.lists() },
        (old) => (old ? { ...old, data: old.data.filter((r) => r.id !== id) } : old),
      );
      return { previousLists };
    },
    onError: (_err, _vars, context) => {
      context?.previousLists?.forEach(([key, data]) => {
        queryClient.setQueryData(key, data);
      });
    },
    onSettled: (_data, _err, { id }) => {
      queryClient.invalidateQueries({ queryKey: requestKeys.lists() });
      queryClient.invalidateQueries({ queryKey: requestKeys.detail(id) });
    },
  });
}
