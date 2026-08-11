"use client";

import { Copy, Redo2, Trash2, Undo2 } from "lucide-react";

import { Button } from "@/components/ui/button";

export function WorkflowToolbar({
  isDraft,
  isSaving,
  isDeleting,
  canUndo,
  canRedo,
  onUndo,
  onRedo,
  onSaveDraft,
  onPublish,
  onDuplicate,
  onDelete,
}: {
  isDraft: boolean;
  isSaving: boolean;
  isDeleting: boolean;
  canUndo: boolean;
  canRedo: boolean;
  onUndo: () => void;
  onRedo: () => void;
  onSaveDraft: () => void;
  onPublish: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
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
      {isDraft && (
        <Button variant="outline" size="sm" disabled={isDeleting} onClick={onDelete}>
          <Trash2 className="size-4" /> Delete draft
        </Button>
      )}
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
