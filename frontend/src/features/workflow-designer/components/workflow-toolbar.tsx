"use client";

import { Copy, Redo2, Undo2 } from "lucide-react";

import { Button } from "@/components/ui/button";

export function WorkflowToolbar({
  isDraft,
  isSaving,
  canUndo,
  canRedo,
  onUndo,
  onRedo,
  onSaveDraft,
  onPublish,
  onDuplicate,
}: {
  isDraft: boolean;
  isSaving: boolean;
  canUndo: boolean;
  canRedo: boolean;
  onUndo: () => void;
  onRedo: () => void;
  onSaveDraft: () => void;
  onPublish: () => void;
  onDuplicate: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button variant="outline" size="icon" aria-label="Undo" disabled={!canUndo || !isDraft} onClick={onUndo}>
        <Undo2 className="size-4" />
      </Button>
      <Button variant="outline" size="icon" aria-label="Redo" disabled={!canRedo || !isDraft} onClick={onRedo}>
        <Redo2 className="size-4" />
      </Button>
      <Button variant="outline" size="sm" onClick={onDuplicate}>
        <Copy className="size-4" /> Duplicate
      </Button>
      <div className="ml-auto flex items-center gap-2">
        {isDraft && (
          <Button variant="outline" size="sm" disabled={isSaving} onClick={onSaveDraft}>
            {isSaving ? "Saving…" : "Save draft"}
          </Button>
        )}
        {isDraft && (
          <Button size="sm" onClick={onPublish}>
            Publish
          </Button>
        )}
      </div>
    </div>
  );
}
