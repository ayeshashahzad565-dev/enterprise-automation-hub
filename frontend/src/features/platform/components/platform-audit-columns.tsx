"use client";

import type { ColumnDef } from "@tanstack/react-table";

import { getAuditActionMeta } from "@/features/platform/lib/audit-action-meta";
import type { PlatformAuditEntry } from "@/types/platform";

/** Columns for the full, filterable `/platform/audit` page — `company_id`
 * is resolved to a name via the `companyNamesById` map built from the
 * already-fetched companies list (see `PlatformActivityList`'s own
 * docstring for why this is never a second backend call). */
export function buildPlatformAuditColumns(
  companyNamesById: Map<string, string>,
): ColumnDef<PlatformAuditEntry>[] {
  return [
    {
      accessorKey: "action",
      header: "Action",
      cell: ({ row }) => {
        const meta = getAuditActionMeta(row.original.action);
        const Icon = meta.icon;
        return (
          <span className="flex items-center gap-1.5">
            <Icon className="size-4 text-muted-foreground" aria-hidden />
            {meta.label}
          </span>
        );
      },
    },
    {
      id: "company",
      header: "Company",
      cell: ({ row }) => {
        const companyId = row.original.company_id;
        if (!companyId) return <span className="text-muted-foreground">Platform-level</span>;
        return companyNamesById.get(companyId) ?? (
          <span className="font-mono text-xs text-muted-foreground">{companyId}</span>
        );
      },
    },
    {
      accessorKey: "actor_id",
      header: "Actor",
      cell: ({ row }) =>
        row.original.actor_id ? (
          <span className="font-mono text-xs">{row.original.actor_id}</span>
        ) : (
          <span className="text-muted-foreground">System</span>
        ),
    },
    {
      accessorKey: "request_id",
      header: "Request",
      cell: ({ row }) =>
        row.original.request_id ? (
          <span className="font-mono text-xs">{row.original.request_id}</span>
        ) : (
          "—"
        ),
    },
    {
      accessorKey: "created_at",
      header: "When",
      cell: ({ row }) => new Date(row.original.created_at).toLocaleString(),
    },
  ];
}
