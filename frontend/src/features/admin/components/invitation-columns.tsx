"use client";

import type { ColumnDef } from "@tanstack/react-table";
import { formatDistanceToNow } from "date-fns";
import { MoreHorizontal, RotateCw, Ban } from "lucide-react";

import { InvitationStatusBadge } from "@/components/patterns/status-badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { Invitation } from "@/types/admin";

/** Resend/revoke are both valid only while the invitation's *persisted*
 * status is still `pending` — which includes the computed `expired`
 * effective status (see `InvitationService._require_pending`'s own
 * docstring: an expired-but-unaccepted invitation may still be resent or
 * revoked; only `accepted`/`revoked` are terminal). */
function isActionable(invitation: Invitation): boolean {
  return invitation.effective_status === "pending" || invitation.effective_status === "expired";
}

export interface InvitationRowActions {
  onResend: (invitation: Invitation) => void;
  onRevoke: (invitation: Invitation) => void;
  resendingId: string | null;
}

export function buildInvitationColumns(actions: InvitationRowActions): ColumnDef<Invitation>[] {
  return [
    {
      accessorKey: "full_name",
      header: "Name",
      cell: ({ row }) => <span className="font-medium">{row.original.full_name}</span>,
    },
    {
      accessorKey: "email",
      header: "Email",
      cell: ({ row }) => <span className="text-sm text-muted-foreground">{row.original.email}</span>,
    },
    {
      accessorKey: "role",
      header: "Role",
      cell: ({ row }) => <span className="capitalize">{row.original.role}</span>,
    },
    {
      accessorKey: "department",
      header: "Department",
      cell: ({ row }) => row.original.department ?? "—",
    },
    {
      accessorKey: "effective_status",
      header: "Status",
      cell: ({ row }) => <InvitationStatusBadge status={row.original.effective_status} />,
    },
    {
      accessorKey: "created_at",
      header: "Invited",
      cell: ({ row }) => (
        <span className="text-sm text-muted-foreground">
          {formatDistanceToNow(new Date(row.original.created_at), { addSuffix: true })}
        </span>
      ),
    },
    {
      accessorKey: "expires_at",
      header: "Expires",
      cell: ({ row }) => (
        <span className="text-sm text-muted-foreground">
          {formatDistanceToNow(new Date(row.original.expires_at), { addSuffix: true })}
        </span>
      ),
    },
    {
      id: "actions",
      header: () => <span className="sr-only">Quick actions</span>,
      cell: ({ row }) => {
        const invitation = row.original;
        if (!isActionable(invitation)) {
          return null;
        }
        const isResendingThisRow = actions.resendingId === invitation.id;
        return (
          <DropdownMenu>
            <DropdownMenuTrigger render={<Button variant="ghost" size="icon" />}>
              <MoreHorizontal className="size-4" />
              <span className="sr-only">Open quick actions</span>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem
                disabled={isResendingThisRow}
                onClick={() => actions.onResend(invitation)}
              >
                <RotateCw className="size-4" /> {isResendingThisRow ? "Resending…" : "Resend"}
              </DropdownMenuItem>
              <DropdownMenuItem variant="destructive" onClick={() => actions.onRevoke(invitation)}>
                <Ban className="size-4" /> Revoke
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        );
      },
      enableSorting: false,
      enableHiding: false,
    },
  ];
}
