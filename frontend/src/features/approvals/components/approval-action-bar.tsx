"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { DecisionDialog, type DecisionAction } from "@/features/approvals/components/decision-dialog";

/** Renders identically inside the full page, the split-view pane, and the side-preview sheet. */
export function ApprovalActionBar({
  isSubmitting,
  onApprove,
  onReject,
}: {
  isSubmitting?: boolean;
  onApprove: (note: string | undefined) => void;
  onReject: (note: string) => void;
}) {
  const [pendingAction, setPendingAction] = useState<DecisionAction | null>(null);

  function handleSubmit(note: string | undefined) {
    if (pendingAction === "approve") {
      onApprove(note);
    } else if (pendingAction) {
      onReject(note ?? "");
    }
    setPendingAction(null);
  }

  return (
    <div className="flex flex-wrap justify-end gap-2 border-t bg-muted/30 p-4">
      <Button
        variant="outline"
        size="sm"
        disabled={isSubmitting}
        onClick={() => setPendingAction("request_changes")}
      >
        Request changes
      </Button>
      <Button
        variant="destructive"
        size="sm"
        disabled={isSubmitting}
        onClick={() => setPendingAction("reject")}
      >
        Reject
      </Button>
      <Button size="sm" disabled={isSubmitting} onClick={() => setPendingAction("approve")}>
        Approve
      </Button>
      {pendingAction && (
        <DecisionDialog
          open={Boolean(pendingAction)}
          onOpenChange={(open) => !open && setPendingAction(null)}
          action={pendingAction}
          isSubmitting={isSubmitting}
          onSubmit={handleSubmit}
        />
      )}
    </div>
  );
}
