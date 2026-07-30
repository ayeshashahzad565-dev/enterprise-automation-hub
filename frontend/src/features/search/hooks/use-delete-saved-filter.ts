"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { searchKeys } from "@/features/search/query-keys";
import { searchService } from "@/services/search-service";

export function useDeleteSavedFilter() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => searchService.deleteSavedFilter(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: searchKeys.savedFilters() });
    },
  });
}
