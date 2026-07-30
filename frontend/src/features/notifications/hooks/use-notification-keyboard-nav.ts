"use client";

import { useEffect } from "react";

/**
 * Keyboard navigation scoped to the Notifications page only (not global),
 * the same shape as Approvals' `useApprovalKeyboardNav` — j/k move the
 * focused row, Enter opens it, r marks it read, e archives it.
 */
export function useNotificationKeyboardNav({
  rowCount,
  focusedIndex,
  onFocusChange,
  onOpen,
  onMarkRead,
  onArchive,
  enabled = true,
}: {
  rowCount: number;
  focusedIndex: number;
  onFocusChange: (index: number) => void;
  onOpen: (index: number) => void;
  onMarkRead: (index: number) => void;
  onArchive: (index: number) => void;
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
        case "r":
          if (focusedIndex >= 0) onMarkRead(focusedIndex);
          break;
        case "e":
          if (focusedIndex >= 0) onArchive(focusedIndex);
          break;
        default:
          break;
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [enabled, rowCount, focusedIndex, onFocusChange, onOpen, onMarkRead, onArchive]);
}
