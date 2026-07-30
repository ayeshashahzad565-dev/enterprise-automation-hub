"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";

export type DecisionAction = "approve" | "reject" | "request_changes";

/**
 * "Request changes" is not a distinct backend outcome — it calls the same
 * `reject_stage` endpoint as "Reject" (see the Phase 3 migration plan's
 * scoping decision). Both share this dialog; only the copy differs.
 */
const COPY: Record<
  DecisionAction,
  { title: string; description: string; confirmLabel: string; noteRequired: boolean }
> = {
  approve: {
    title: "Approve this request?",
    description: "You can optionally add a note for the record.",
    confirmLabel: "Approve",
    noteRequired: false,
  },
  reject: {
    title: "Reject this request?",
    description: "A reason is required — it's shown to the requester.",
    confirmLabel: "Reject",
    noteRequired: true,
  },
  request_changes: {
    title: "Request changes?",
    description:
      "Explain what needs to change. This is recorded as a rejection — the requester must submit a new request.",
    confirmLabel: "Request changes",
    noteRequired: true,
  },
};

export function DecisionDialog({
  open,
  onOpenChange,
  action,
  isSubmitting,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  action: DecisionAction;
  isSubmitting?: boolean;
  onSubmit: (note: string | undefined) => void;
}) {
  const [note, setNote] = useState("");
  const copy = COPY[action];
  const canSubmit = !copy.noteRequired || note.trim().length > 0;

  useEffect(() => {
    if (open) setNote("");
  }, [open, action]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{copy.title}</DialogTitle>
          <DialogDescription>{copy.description}</DialogDescription>
        </DialogHeader>
        <Textarea
          placeholder={copy.noteRequired ? "Reason (required)..." : "Note (optional)..."}
          rows={4}
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
        <DialogFooter>
          <Button variant="outline" disabled={isSubmitting} onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant={action === "approve" ? "default" : "destructive"}
            disabled={!canSubmit || isSubmitting}
            onClick={() => onSubmit(note.trim() || undefined)}
          >
            {isSubmitting ? "Working…" : copy.confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
