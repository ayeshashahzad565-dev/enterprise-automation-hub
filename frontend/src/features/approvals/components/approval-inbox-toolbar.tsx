"use client";

import type { Table } from "@tanstack/react-table";
import { LayoutGrid, LayoutList } from "lucide-react";
import type { ReactNode } from "react";

import { DataTableToolbar } from "@/components/patterns/data-table/data-table-toolbar";
import { SavedViewsMenu } from "@/components/patterns/saved-views-menu";
import { Button } from "@/components/ui/button";
import type { SavedView } from "@/features/approvals/hooks/use-saved-views";

/**
 * Extends the shared `DataTableToolbar` with two approval-specific
 * concerns: a Saved Views menu (frontend-only, since no backend concept
 * of a saved view exists) and the table/split view-mode toggle.
 */
export function ApprovalInboxToolbar<TData>({
  table,
  searchValue,
  onSearchChange,
  filters,
  filtersDisabled,
  filtersDisabledReason,
  savedViews,
  onApplyView,
  onSaveCurrentView,
  onRemoveView,
  viewMode,
  onToggleViewMode,
  bulkActions,
}: {
  table: Table<TData>;
  searchValue: string;
  onSearchChange: (value: string) => void;
  filters?: ReactNode;
  filtersDisabled?: boolean;
  filtersDisabledReason?: string;
  savedViews: SavedView[];
  onApplyView: (view: SavedView) => void;
  onSaveCurrentView: (name: string) => void;
  onRemoveView: (name: string) => void;
  viewMode: "table" | "split";
  onToggleViewMode: () => void;
  bulkActions?: ReactNode;
}) {
  return (
    <DataTableToolbar
      table={table}
      searchValue={searchValue}
      onSearchChange={onSearchChange}
      searchPlaceholder="Search this page..."
      filters={filters}
      filtersDisabled={filtersDisabled}
      filtersDisabledReason={filtersDisabledReason}
      primaryAction={
        <>
          {bulkActions}
          <SavedViewsMenu
            views={savedViews}
            onApply={onApplyView}
            onSave={onSaveCurrentView}
            onRemove={onRemoveView}
          />
          <Button variant="outline" size="sm" onClick={onToggleViewMode}>
            {viewMode === "table" ? (
              <LayoutGrid className="size-4" />
            ) : (
              <LayoutList className="size-4" />
            )}
            {viewMode === "table" ? "Split view" : "Table view"}
          </Button>
        </>
      }
    />
  );
}
