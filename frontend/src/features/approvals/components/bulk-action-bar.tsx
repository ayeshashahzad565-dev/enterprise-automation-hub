"use client";

import { Button } from "@/components/ui/button";

/** Floating bulk-action bar — mirrors the Requests list's bulk-withdraw bar. */
export function BulkActionBar({
  selectedCount,
  isSubmitting,
  onApprove,
  onReject,
  onClear,
}: {
  selectedCount: number;
  isSubmitting?: boolean;
  onApprove: () => void;
  onReject: () => void;
  onClear: () => void;
}) {
  if (selectedCount === 0) return null;

  return (
    <div className="flex items-center gap-2">
      <span className="text-sm text-muted-foreground">{selectedCount} selected</span>
      <Button variant="outline" size="sm" disabled={isSubmitting} onClick={onClear}>
        Clear
      </Button>
      <Button variant="destructive" size="sm" disabled={isSubmitting} onClick={onReject}>
        Reject
      </Button>
      <Button size="sm" disabled={isSubmitting} onClick={onApprove}>
        Approve
      </Button>
    </div>
  );
}
