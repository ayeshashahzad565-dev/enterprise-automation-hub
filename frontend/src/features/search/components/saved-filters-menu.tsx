"use client";

import { BookmarkPlus, Star, Trash2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { SaveFilterDialog } from "@/features/search/components/save-filter-dialog";
import { useDeleteSavedFilter } from "@/features/search/hooks/use-delete-saved-filter";
import { useSavedFilters } from "@/features/search/hooks/use-saved-filters";
import { notifyError, notifySuccess } from "@/lib/toast";
import type { SavedFilter, SearchEntityType } from "@/types/search";

export function SavedFiltersMenu({
  queryText,
  entityTypes,
  onApply,
}: {
  queryText: string;
  entityTypes: SearchEntityType[];
  onApply: (filter: SavedFilter) => void;
}) {
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const savedFiltersQuery = useSavedFilters();
  const deleteSavedFilter = useDeleteSavedFilter();
  const savedFilters = savedFiltersQuery.data ?? [];

  async function handleDelete(id: string, name: string) {
    try {
      await deleteSavedFilter.mutateAsync(id);
      notifySuccess(`"${name}" deleted.`);
    } catch (error) {
      notifyError(error, "Couldn't delete this saved filter.");
    }
  }

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger render={<Button variant="outline" size="sm" />}>
          <Star className="size-4" /> Saved filters
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-64">
          <DropdownMenuItem
            disabled={!queryText.trim()}
            onClick={() => setSaveDialogOpen(true)}
          >
            <BookmarkPlus className="size-4" /> Save current search
          </DropdownMenuItem>
          {savedFilters.length > 0 && <DropdownMenuSeparator />}
          {savedFilters.map((filter) => (
            <DropdownMenuItem
              key={filter.id}
              className="flex items-center justify-between gap-2"
              onClick={() => onApply(filter)}
            >
              <span className="truncate">{filter.name}</span>
              <button
                type="button"
                className="shrink-0 rounded p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                aria-label={`Delete saved filter "${filter.name}"`}
                onClick={(event) => {
                  event.stopPropagation();
                  void handleDelete(filter.id, filter.name);
                }}
              >
                <Trash2 className="size-3.5" />
              </button>
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
      <SaveFilterDialog
        open={saveDialogOpen}
        onOpenChange={setSaveDialogOpen}
        queryText={queryText}
        entityTypes={entityTypes}
      />
    </>
  );
}
