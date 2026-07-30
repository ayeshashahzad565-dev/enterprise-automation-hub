"use client";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { diffStages, summarizeDiff } from "@/features/workflow-designer/lib/diff-stages";
import { VersionDiffView } from "@/features/workflow-designer/components/version-diff-view";
import type { StageDefinition } from "@/types/workflow-definition";

/** Publish confirmation: a change summary (vs. the currently active version, if any) plus the full stage diff, before calling activate. */
export function PublishConfirmDialog({
  open,
  onOpenChange,
  candidateStages,
  activeStages,
  isPublishing,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  candidateStages: StageDefinition[];
  activeStages: StageDefinition[] | null;
  isPublishing: boolean;
  onConfirm: () => void;
}) {
  const rows = diffStages(activeStages ?? [], candidateStages);
  const summary = summarizeDiff(rows);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[80vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Publish this workflow?</DialogTitle>
          <DialogDescription>
            {activeStages
              ? `This replaces the currently active version. ${summary.added} added, ${summary.removed} removed, ${summary.changed} changed.`
              : "This will become the active version for this request type."}
          </DialogDescription>
        </DialogHeader>
        <VersionDiffView before={activeStages ?? []} after={candidateStages} />
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPublishing}>
            Cancel
          </Button>
          <Button onClick={onConfirm} disabled={isPublishing}>
            {isPublishing ? "Publishing…" : "Publish"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
