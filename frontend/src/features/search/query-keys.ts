import type { SearchParams } from "@/types/search";

/** Centralized TanStack Query key factory for the enterprise search feature. */
export const searchKeys = {
  all: ["search"] as const,
  results: (params: SearchParams) => [...searchKeys.all, "results", params] as const,
  savedFilters: () => [...searchKeys.all, "saved-filters"] as const,
  history: () => [...searchKeys.all, "history"] as const,
};
