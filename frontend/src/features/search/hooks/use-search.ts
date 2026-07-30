"use client";

import { useQuery } from "@tanstack/react-query";

import { searchKeys } from "@/features/search/query-keys";
import { searchService } from "@/services/search-service";
import type { SearchParams } from "@/types/search";

/** `enabled: false` for a blank query — matches every other search-as-
 * you-type surface in this app (`CommandPalette`'s own request search),
 * which never fires a request for an empty term. */
export function useSearch(params: SearchParams) {
  return useQuery({
    queryKey: searchKeys.results(params),
    queryFn: () => searchService.search(params),
    enabled: params.q.trim().length > 0,
    staleTime: 10_000,
  });
}
