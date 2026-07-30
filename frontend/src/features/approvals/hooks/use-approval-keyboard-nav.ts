"use client";

import { useEffect } from "react";

/**
 * Keyboard navigation scoped to the Approval Inbox page only (not global,
 * unlike the command palette / "?" shortcuts dialog) — j/k move the
 * focused row, Enter opens the preview, a/x approve/reject the focused
 * row, v toggles split view.
 */
export function useApprovalKeyboardNav({
  rowCount,
  focusedIndex,
  onFocusChange,
  onOpen,
  onApprove,
  onReject,
  onToggleSplitView,
  enabled = true,
}: {
  rowCount: number;
  focusedIndex: number;
  onFocusChange: (index: number) => void;
  onOpen: (index: number) => void;
  onApprove: (index: number) => void;
  onReject: (index: number) => void;
  onToggleSplitView: () => void;
  enabled?: boolean;
}) {
  useEffect(() => {
    if (!enabled || rowCount === 0) return;

    function handleKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const isTyping = target?.tagName === "INPUT" || target?.tagName === "TEXTAREA";
      if (isTyping) return;

      switch (event.key) {
        case "j":
          event.preventDefault();
          onFocusChange(Math.min(focusedIndex + 1, rowCount - 1));
          break;
        case "k":
          event.preventDefault();
          onFocusChange(Math.max(focusedIndex - 1, 0));
          break;
        case "Enter":
          if (focusedIndex >= 0) onOpen(focusedIndex);
          break;
        case "a":
          if (focusedIndex >= 0) onApprove(focusedIndex);
          break;
        case "x":
          if (focusedIndex >= 0) onReject(focusedIndex);
          break;
        case "v":
          onToggleSplitView();
          break;
        default:
          break;
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [enabled, rowCount, focusedIndex, onFocusChange, onOpen, onApprove, onReject, onToggleSplitView]);
}
