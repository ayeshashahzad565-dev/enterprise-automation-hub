"use client";

import { SearchX } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

import { DataTablePagination } from "@/components/patterns/data-table/data-table-pagination";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { PageHeader } from "@/components/patterns/page-header";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { groupByEntityType, SearchResultList } from "@/features/search/components/search-result-list";
import { RecentSearchesList } from "@/features/search/components/recent-searches-list";
import { SavedFiltersMenu } from "@/features/search/components/saved-filters-menu";
import { SearchFiltersPanel } from "@/features/search/components/search-filters-panel";
import { getSearchResultHref } from "@/features/search/lib/result-href";
import { useSearch } from "@/features/search/hooks/use-search";
import { useCurrentUser } from "@/features/profile/hooks/use-current-user";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import type { SavedFilter, SearchEntityType } from "@/types/search";

const SEARCH_DEBOUNCE_MS = 300;

export default function SearchPage() {
  return (
    <Suspense
      fallback={
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      }
    >
      <SearchPageContent />
    </Suspense>
  );
}

function SearchPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [query, setQuery] = useState(searchParams.get("q") ?? "");
  const [entityTypes, setEntityTypes] = useState<SearchEntityType[]>([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [activeId, setActiveId] = useState<string | null>(null);

  const debouncedQuery = useDebouncedValue(query, SEARCH_DEBOUNCE_MS);
  const { data: profile } = useCurrentUser();

  const searchQuery = useSearch({
    q: debouncedQuery,
    entityTypes: entityTypes.length > 0 ? entityTypes : undefined,
    page,
    pageSize,
  });

  const results = useMemo(() => searchQuery.data?.data ?? [], [searchQuery.data]);
  const orderedResults = useMemo(
    () => groupByEntityType(results).flatMap(([, items]) => items),
    [results],
  );

  useEffect(() => {
    setActiveId(orderedResults[0]?.id ?? null);
  }, [orderedResults]);

  function applySavedFilter(filter: SavedFilter) {
    setQuery(filter.query_text);
    setEntityTypes(filter.entity_types ?? []);
    setPage(1);
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (orderedResults.length === 0) return;
    const currentIndex = orderedResults.findIndex((r) => r.id === activeId);
    if (event.key === "ArrowDown") {
      event.preventDefault();
      const next = orderedResults[Math.min(currentIndex + 1, orderedResults.length - 1)];
      if (next) setActiveId(next.id);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      const previous = orderedResults[Math.max(currentIndex - 1, 0)];
      if (previous) setActiveId(previous.id);
    } else if (event.key === "Enter") {
      const active = orderedResults.find((r) => r.id === activeId);
      const href = active ? getSearchResultHref(active) : null;
      if (href) {
        event.preventDefault();
        router.push(href);
      }
    }
  }

  const hasQuery = debouncedQuery.trim().length > 0;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Search"
        description="Search across requests, workflows, users, departments, notifications, audit logs, and attachments."
      />

      <div className="flex flex-wrap items-center gap-2">
        <Input
          autoFocus
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setPage(1);
          }}
          onKeyDown={handleKeyDown}
          placeholder="Search everything…"
          className="max-w-md"
          aria-label="Search"
        />
        <SavedFiltersMenu queryText={query} entityTypes={entityTypes} onApply={applySavedFilter} />
      </div>

      <SearchFiltersPanel
        selected={entityTypes}
        onChange={(types) => {
          setEntityTypes(types);
          setPage(1);
        }}
        isAdmin={profile?.role === "admin"}
      />

      {!hasQuery ? (
        <RecentSearchesList
          onSelect={(value) => {
            setQuery(value);
            setPage(1);
          }}
        />
      ) : searchQuery.isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : searchQuery.isError ? (
        <ErrorState message="Couldn't run this search." onRetry={() => searchQuery.refetch()} />
      ) : results.length === 0 ? (
        <EmptyState
          icon={SearchX}
          title="No results"
          description="Try a different query or broaden your filters."
        />
      ) : (
        <>
          <SearchResultList results={results} activeId={activeId} onHover={setActiveId} />
          <DataTablePagination
            page={searchQuery.data?.pagination.page ?? 1}
            pageSize={searchQuery.data?.pagination.page_size ?? pageSize}
            totalRecords={searchQuery.data?.pagination.total_records ?? 0}
            totalPages={searchQuery.data?.pagination.total_pages ?? 1}
            onPageChange={setPage}
            onPageSizeChange={(size) => {
              setPageSize(size);
              setPage(1);
            }}
          />
        </>
      )}
    </div>
  );
}
