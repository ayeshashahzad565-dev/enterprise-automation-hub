"use client";

import { ExternalLink } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { ApprovalDetailContent } from "@/features/approvals/components/approval-detail-content";
import { ROUTES } from "@/utils/constants";

/** The "side preview panel" UX requirement — a slide-over quick look, one click from a full page. */
export function ApprovalPreviewSheet({
  item,
  open,
  onOpenChange,
  onDecided,
}: {
  item: { stageId: string; requestId: string; stageVersion: number; requestTitle: string } | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDecided?: () => void;
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="flex w-full flex-col sm:max-w-lg">
        <SheetHeader className="flex-row items-center justify-between gap-2 pr-10">
          <SheetTitle className="truncate">{item?.requestTitle ?? "Request"}</SheetTitle>
          {item && (
            <Button variant="ghost" size="sm" render={<Link href={ROUTES.approval(item.stageId)} />}>
              <ExternalLink className="size-4" /> Open full page
            </Button>
          )}
        </SheetHeader>
        {item && (
          <ApprovalDetailContent
            requestId={item.requestId}
            stageId={item.stageId}
            stageVersion={item.stageVersion}
            onDecided={() => {
              onDecided?.();
              onOpenChange(false);
            }}
          />
        )}
      </SheetContent>
    </Sheet>
  );
}
