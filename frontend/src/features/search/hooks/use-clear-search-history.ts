"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { searchKeys } from "@/features/search/query-keys";
import { searchService } from "@/services/search-service";

export function useClearSearchHistory() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => searchService.clearSearchHistory(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: searchKeys.history() });
    },
  });
}
