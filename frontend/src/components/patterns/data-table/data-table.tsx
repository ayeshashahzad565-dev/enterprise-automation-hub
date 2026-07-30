"use client";

import { flexRender, type Table as TanstackTable } from "@tanstack/react-table";
import { useEffect, useState } from "react";
import type { OnChangeFn, VisibilityState } from "@tanstack/react-table";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

/**
 * Generic, reusable table renderer over an externally-constructed
 * `@tanstack/react-table` instance — the feature-level page owns the
 * `useReactTable(...)` call (so its toolbar/pagination/view-options
 * siblings can share the same `table` instance), this component only
 * renders the header/body given that instance.
 */
export function DataTable<TData>({
  table,
  onRowClick,
  emptyMessage = "No results.",
}: {
  table: TanstackTable<TData>;
  onRowClick?: (row: TData) => void;
  emptyMessage?: string;
}) {
  const columnCount = table.getAllLeafColumns().length;

  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="max-h-[70vh] overflow-auto">
        <Table>
          <TableHeader className="sticky top-0 z-10 bg-card">
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <TableHead key={header.id}>
                    {header.isPlaceholder
                      ? null
                      : flexRender(header.column.columnDef.header, header.getContext())}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {table.getRowModel().rows.length ? (
              table.getRowModel().rows.map((row) => (
                <TableRow
                  key={row.id}
                  data-state={row.getIsSelected() ? "selected" : undefined}
                  onClick={() => onRowClick?.(row.original)}
                  className={cn(onRowClick && "cursor-pointer")}
                >
                  {row.getVisibleCells().map((cell) => {
                    const stopsRowClick = cell.column.id === "select" || cell.column.id === "actions";
                    return (
                      <TableCell
                        key={cell.id}
                        onClick={(event) => stopsRowClick && event.stopPropagation()}
                      >
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </TableCell>
                    );
                  })}
                </TableRow>
              ))
            ) : (
              <TableRow>
                <TableCell colSpan={columnCount} className="h-24 text-center text-muted-foreground">
                  {emptyMessage}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

/** Column-visibility state, persisted to localStorage under `storageKey`. */
export function usePersistedColumnVisibility(
  storageKey: string,
): [VisibilityState, OnChangeFn<VisibilityState>] {
  const [visibility, setVisibility] = useState<VisibilityState>({});

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(storageKey);
      if (raw) setVisibility(JSON.parse(raw) as VisibilityState);
    } catch {
      // ignore corrupted preference
    }
  }, [storageKey]);

  const onVisibilityChange: OnChangeFn<VisibilityState> = (updater) => {
    setVisibility((old) => {
      const next = typeof updater === "function" ? updater(old) : updater;
      try {
        window.localStorage.setItem(storageKey, JSON.stringify(next));
      } catch {
        // storage unavailable — preference simply won't persist
      }
      return next;
    });
  };

  return [visibility, onVisibilityChange];
}
