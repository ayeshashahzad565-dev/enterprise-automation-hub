"use client";

import type { Table } from "@tanstack/react-table";
import { Search } from "lucide-react";
import type { ReactNode } from "react";

import { DataTableViewOptions } from "@/components/patterns/data-table/data-table-view-options";
import { Input } from "@/components/ui/input";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

export function DataTableToolbar<TData>({
  table,
  searchValue,
  onSearchChange,
  searchPlaceholder = "Search...",
  filters,
  filtersDisabled,
  filtersDisabledReason,
  primaryAction,
}: {
  table: Table<TData>;
  searchValue: string;
  onSearchChange: (value: string) => void;
  searchPlaceholder?: string;
  filters?: ReactNode;
  filtersDisabled?: boolean;
  filtersDisabledReason?: string;
  primaryAction?: ReactNode;
}) {
  const filterControls = (
    <div className={filtersDisabled ? "pointer-events-none opacity-50" : undefined}>{filters}</div>
  );

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="relative w-full max-w-xs">
        <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={searchValue}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder={searchPlaceholder}
          className="pl-8"
        />
      </div>
      {filters &&
        (filtersDisabled && filtersDisabledReason ? (
          <Tooltip>
            <TooltipTrigger>{filterControls}</TooltipTrigger>
            <TooltipContent>{filtersDisabledReason}</TooltipContent>
          </Tooltip>
        ) : (
          filterControls
        ))}
      <div className="ml-auto flex items-center gap-2 border-l pl-2">
        <DataTableViewOptions table={table} />
        {primaryAction}
      </div>
    </div>
  );
}
