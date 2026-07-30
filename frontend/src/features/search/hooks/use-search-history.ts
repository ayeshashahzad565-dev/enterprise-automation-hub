"use client";

import { useQuery } from "@tanstack/react-query";

import { searchKeys } from "@/features/search/query-keys";
import { searchService } from "@/services/search-service";

export function useSearchHistory() {
  return useQuery({
    queryKey: searchKeys.history(),
    queryFn: () => searchService.listSearchHistory(),
    staleTime: 10_000,
  });
}
