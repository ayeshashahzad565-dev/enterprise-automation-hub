import { apiClient } from "@/lib/api/client";
import type {
  CreateSavedFilterBody,
  SavedFilter,
  SearchHistoryEntry,
  SearchParams,
  SearchResult,
} from "@/types/search";

function buildQuery(params: object): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

export const searchService = {
  search: (params: SearchParams) =>
    apiClient.getList<SearchResult>(
      `/search${buildQuery({
        q: params.q,
        entity_types: params.entityTypes?.join(","),
        page: params.page,
        page_size: params.pageSize,
      })}`,
    ),
  listSavedFilters: () => apiClient.get<SavedFilter[]>("/search/saved-filters"),
  createSavedFilter: (body: CreateSavedFilterBody) =>
    apiClient.post<SavedFilter>("/search/saved-filters", body),
  deleteSavedFilter: (id: string) => apiClient.delete<void>(`/search/saved-filters/${id}`),
  listSearchHistory: () => apiClient.get<SearchHistoryEntry[]>("/search/history"),
  clearSearchHistory: () => apiClient.delete<void>("/search/history"),
};
