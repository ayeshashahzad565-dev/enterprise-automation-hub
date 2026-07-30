"use client";

import { History, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useClearSearchHistory } from "@/features/search/hooks/use-clear-search-history";
import { useSearchHistory } from "@/features/search/hooks/use-search-history";
import { notifyError } from "@/lib/toast";

export function RecentSearchesList({ onSelect }: { onSelect: (query: string) => void }) {
  const historyQuery = useSearchHistory();
  const clearHistory = useClearSearchHistory();
  const entries = historyQuery.data ?? [];

  if (entries.length === 0) {
    return null;
  }

  async function handleClear() {
    try {
      await clearHistory.mutateAsync();
    } catch (error) {
      notifyError(error, "Couldn't clear search history.");
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <History className="size-3.5" /> Recent searches
        </p>
        <Button
          variant="ghost"
          size="sm"
          className="h-6 px-2 text-xs text-muted-foreground"
          disabled={clearHistory.isPending}
          onClick={handleClear}
        >
          <X className="size-3" /> Clear
        </Button>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {entries.map((entry) => (
          <button
            key={entry.id}
            type="button"
            className="rounded-full border px-3 py-1 text-xs text-muted-foreground hover:bg-muted"
            onClick={() => onSelect(entry.query_text)}
          >
            {entry.query_text}
          </button>
        ))}
      </div>
    </div>
  );
}
