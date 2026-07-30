"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { searchKeys } from "@/features/search/query-keys";
import { searchService } from "@/services/search-service";
import type { CreateSavedFilterBody } from "@/types/search";

export function useCreateSavedFilter() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (body: CreateSavedFilterBody) => searchService.createSavedFilter(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: searchKeys.savedFilters() });
    },
  });
}
