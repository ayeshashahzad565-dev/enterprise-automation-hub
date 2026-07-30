"use client";

import type { ColumnDef } from "@tanstack/react-table";
import { formatDistanceToNow } from "date-fns";
import { Check, Eye, MoreHorizontal, X } from "lucide-react";
import Link from "next/link";

import { DataTableColumnHeader } from "@/components/patterns/data-table/data-table-column-header";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { ApprovalInboxItem } from "@/types/approval";
import { ROUTES } from "@/utils/constants";

export interface ApprovalRowActions {
  onApprove: (item: ApprovalInboxItem) => void;
  onReject: (item: ApprovalInboxItem) => void;
}

export function buildApprovalColumns(actions: ApprovalRowActions): ColumnDef<ApprovalInboxItem>[] {
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
      accessorKey: "request_title",
      header: ({ column }) => <DataTableColumnHeader column={column} title="Request" />,
      cell: ({ row }) => (
        <Link
          href={ROUTES.approval(row.original.stage_id)}
          className="font-medium hover:underline"
        >
          {row.original.request_title}
        </Link>
      ),
      meta: { label: "Request" },
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
      accessorKey: "stage_name",
      header: ({ column }) => <DataTableColumnHeader column={column} title="Stage" />,
      cell: ({ row }) => <span className="text-sm">{row.original.stage_name}</span>,
      meta: { label: "Stage" },
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
      accessorKey: "stage_created_at",
      header: ({ column }) => <DataTableColumnHeader column={column} title="Waiting" />,
      cell: ({ row }) => (
        <span className="text-sm text-muted-foreground">
          {formatDistanceToNow(new Date(row.original.stage_created_at))}
        </span>
      ),
      meta: { label: "Waiting" },
    },
    {
      accessorKey: "requester_id",
      header: ({ column }) => <DataTableColumnHeader column={column} title="Requester" />,
      cell: ({ row }) => (
        <span className="font-mono text-xs text-muted-foreground">
          {row.original.requester_id.slice(0, 8)}…
        </span>
      ),
      meta: { label: "Requester" },
    },
    {
      id: "actions",
      header: () => <span className="sr-only">Quick actions</span>,
      cell: ({ row }) => {
        const item = row.original;
        return (
          <div className="flex items-center justify-end gap-1">
            <Button
              variant="ghost"
              size="icon"
              aria-label="Approve"
              onClick={() => actions.onApprove(item)}
            >
              <Check className="size-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Reject"
              onClick={() => actions.onReject(item)}
            >
              <X className="size-4" />
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger render={<Button variant="ghost" size="icon" />}>
                <MoreHorizontal className="size-4" />
                <span className="sr-only">Open quick actions</span>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem render={<Link href={ROUTES.approval(item.stage_id)} />}>
                  <Eye className="size-4" /> Open full page
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        );
      },
      enableSorting: false,
      enableHiding: false,
      meta: { label: "Actions" },
    },
  ];
}
