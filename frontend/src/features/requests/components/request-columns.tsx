"use client";

import type { ColumnDef } from "@tanstack/react-table";
import { formatDistanceToNow } from "date-fns";
import { Copy, Eye, MoreHorizontal, Pencil, Trash2 } from "lucide-react";
import Link from "next/link";

import { DataTableColumnHeader } from "@/components/patterns/data-table/data-table-column-header";
import { StatusBadge } from "@/components/patterns/status-badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { Request } from "@/types/request";
import { ROUTES } from "@/utils/constants";

export interface RequestRowActions {
  canEdit: (request: Request) => boolean;
  canWithdraw: (request: Request) => boolean;
  onWithdraw: (request: Request) => void;
}

export function buildRequestColumns(actions: RequestRowActions): ColumnDef<Request>[] {
  return [
    {
      id: "select",
      header: ({ table }) => (
        <Checkbox
          checked={table.getIsAllPageRowsSelected()}
          indeterminate={table.getIsSomePageRowsSelected() && !table.getIsAllPageRowsSelected()}
          onCheckedChange={(value) => table.toggleAllPageRowsSelected(!!value)}
          aria-label="Select all"
        />
      ),
      cell: ({ row }) => (
        <Checkbox
          checked={row.getIsSelected()}
          onCheckedChange={(value) => row.toggleSelected(!!value)}
          aria-label="Select row"
        />
      ),
      enableSorting: false,
      enableHiding: false,
      meta: { label: "Selection" },
    },
    {
      accessorKey: "title",
      header: ({ column }) => <DataTableColumnHeader column={column} title="Title" />,
      cell: ({ row }) => (
        <Link href={ROUTES.request(row.original.id)} className="font-medium hover:underline">
          {row.original.title}
        </Link>
      ),
      meta: { label: "Title" },
    },
    {
      accessorKey: "request_type",
      header: ({ column }) => <DataTableColumnHeader column={column} title="Type" />,
      cell: ({ row }) => (
        <span className="text-sm text-muted-foreground">{row.original.request_type}</span>
      ),
      meta: { label: "Type" },
    },
    {
      accessorKey: "status",
      header: ({ column }) => <DataTableColumnHeader column={column} title="Status" />,
      cell: ({ row }) => (
        <StatusBadge status={row.original.deleted_at ? "withdrawn" : row.original.status} />
      ),
      meta: { label: "Status" },
    },
    {
      accessorKey: "department",
      header: ({ column }) => <DataTableColumnHeader column={column} title="Department" />,
      cell: ({ row }) => (
        <span className="text-sm text-muted-foreground">{row.original.department ?? "—"}</span>
      ),
      meta: { label: "Department" },
    },
    {
      accessorKey: "created_at",
      header: ({ column }) => <DataTableColumnHeader column={column} title="Created" />,
      cell: ({ row }) => (
        <span className="text-sm text-muted-foreground">
          {formatDistanceToNow(new Date(row.original.created_at), { addSuffix: true })}
        </span>
      ),
      meta: { label: "Created" },
    },
    {
      id: "actions",
      header: () => <span className="sr-only">Quick actions</span>,
      cell: ({ row }) => {
        const request = row.original;
        return (
          <DropdownMenu>
            <DropdownMenuTrigger render={<Button variant="ghost" size="icon" />}>
              <MoreHorizontal className="size-4" />
              <span className="sr-only">Open quick actions</span>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem render={<Link href={ROUTES.request(request.id)} />}>
                <Eye className="size-4" /> View
              </DropdownMenuItem>
              {actions.canEdit(request) && (
                <DropdownMenuItem render={<Link href={`${ROUTES.request(request.id)}?edit=1`} />}>
                  <Pencil className="size-4" /> Edit
                </DropdownMenuItem>
              )}
              <DropdownMenuItem
                onClick={() => navigator.clipboard.writeText(window.location.origin + ROUTES.request(request.id))}
              >
                <Copy className="size-4" /> Copy link
              </DropdownMenuItem>
              {actions.canWithdraw(request) && (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    variant="destructive"
                    onClick={() => actions.onWithdraw(request)}
                  >
                    <Trash2 className="size-4" /> Withdraw
                  </DropdownMenuItem>
                </>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        );
      },
      enableSorting: false,
      enableHiding: false,
      meta: { label: "Actions" },
    },
  ];
}
