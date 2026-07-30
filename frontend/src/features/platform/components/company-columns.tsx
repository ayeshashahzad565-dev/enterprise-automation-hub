"use client";

import type { ColumnDef } from "@tanstack/react-table";
import { MoreHorizontal, Power, PowerOff, RotateCw, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { CompanyStatusBadge } from "@/features/platform/components/company-status-badge";
import type { Company } from "@/types/platform";

export interface CompanyRowActions {
  onSuspend: (company: Company) => void;
  onReactivate: (company: Company) => void;
  onDelete: (company: Company) => void;
  onRestore: (company: Company) => void;
  workingId: string | null;
}

/** Reactivate/delete never need a confirmation dialog here — reactivating
 * is non-destructive, and delete already opens its own `ConfirmDialog`
 * from the page. Suspend also opens a confirm dialog (it locks out every
 * user in the company on their next request), matching the milestone's
 * "confirm dialog only for suspend, since it's the destructive
 * direction" instruction. Restore only ever appears for a soft-deleted
 * row (the page only renders it when "include deleted" is on). */
export function buildCompanyColumns(actions: CompanyRowActions): ColumnDef<Company>[] {
  return [
    {
      accessorKey: "name",
      header: "Name",
      cell: ({ row }) => <span className="font-medium">{row.original.name}</span>,
    },
    {
      accessorKey: "slug",
      header: "Slug",
      cell: ({ row }) => <span className="font-mono text-xs text-muted-foreground">{row.original.slug}</span>,
    },
    {
      id: "status",
      header: "Status",
      cell: ({ row }) => <CompanyStatusBadge company={row.original} />,
    },
    {
      accessorKey: "contact_email",
      header: "Contact email",
      cell: ({ row }) => row.original.contact_email ?? "—",
    },
    {
      accessorKey: "created_at",
      header: "Created",
      cell: ({ row }) => new Date(row.original.created_at).toLocaleDateString(),
    },
    {
      id: "actions",
      header: () => <span className="sr-only">Quick actions</span>,
      cell: ({ row }) => {
        const company = row.original;
        const isWorking = actions.workingId === company.id;
        return (
          <DropdownMenu>
            <DropdownMenuTrigger render={<Button variant="ghost" size="icon" disabled={isWorking} />}>
              <MoreHorizontal className="size-4" />
              <span className="sr-only">Open quick actions</span>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {company.is_deleted ? (
                <DropdownMenuItem onClick={() => actions.onRestore(company)}>
                  <RotateCw className="size-4" /> Restore
                </DropdownMenuItem>
              ) : (
                <>
                  {company.is_active ? (
                    <DropdownMenuItem
                      variant="destructive"
                      onClick={() => actions.onSuspend(company)}
                    >
                      <PowerOff className="size-4" /> Suspend
                    </DropdownMenuItem>
                  ) : (
                    <DropdownMenuItem onClick={() => actions.onReactivate(company)}>
                      <Power className="size-4" /> Reactivate
                    </DropdownMenuItem>
                  )}
                  <DropdownMenuItem variant="destructive" onClick={() => actions.onDelete(company)}>
                    <Trash2 className="size-4" /> Delete
                  </DropdownMenuItem>
                </>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        );
      },
      enableSorting: false,
      enableHiding: false,
    },
  ];
}
