"use client";

import { useQuery } from "@tanstack/react-query";

import { searchKeys } from "@/features/search/query-keys";
import { searchService } from "@/services/search-service";

export function useSavedFilters() {
  return useQuery({
    queryKey: searchKeys.savedFilters(),
    queryFn: () => searchService.listSavedFilters(),
    staleTime: 30_000,
  });
}
