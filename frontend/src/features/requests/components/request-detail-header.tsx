"use client";

import { Copy, MoreHorizontal, Pencil, Trash2 } from "lucide-react";

import { StatusBadge } from "@/components/patterns/status-badge";
import { PageTitle } from "@/components/patterns/typography";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { Request } from "@/types/request";

export function RequestDetailHeader({
  request,
  canEdit,
  canWithdraw,
  onEdit,
  onWithdraw,
}: {
  request: Request;
  canEdit: boolean;
  canWithdraw: boolean;
  onEdit: () => void;
  onWithdraw: () => void;
}) {
  const isWithdrawn = Boolean(request.deleted_at);

  return (
    <div className="space-y-3">
      {isWithdrawn && (
        <div className="rounded-lg border bg-status-withdrawn/40 px-3 py-2 text-sm text-status-withdrawn-foreground">
          This request was withdrawn and can no longer be edited or commented on.
        </div>
      )}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <PageTitle>{request.title}</PageTitle>
          <StatusBadge status={isWithdrawn ? "withdrawn" : request.status} />
        </div>
        <div className="flex items-center gap-2">
          {canEdit && (
            <Button variant="outline" size="sm" onClick={onEdit}>
              <Pencil className="size-4" /> Edit
            </Button>
          )}
          <DropdownMenu>
            <DropdownMenuTrigger render={<Button variant="ghost" size="icon" />}>
              <MoreHorizontal className="size-4" />
              <span className="sr-only">Open quick actions</span>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem
                onClick={() => navigator.clipboard.writeText(window.location.href)}
              >
                <Copy className="size-4" /> Copy link
              </DropdownMenuItem>
              {canWithdraw && (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem variant="destructive" onClick={onWithdraw}>
                    <Trash2 className="size-4" /> Withdraw
                  </DropdownMenuItem>
                </>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
      {request.description && <p className="text-sm text-muted-foreground">{request.description}</p>}
    </div>
  );
}
