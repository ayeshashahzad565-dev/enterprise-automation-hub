"use client";

import { useEffect, useState } from "react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

const SHORTCUTS: ReadonlyArray<{ keys: string; description: string }> = [
  { keys: "Ctrl/Cmd + K", description: "Open the command palette" },
  { keys: "/", description: "Open the command palette (when not typing)" },
  { keys: "?", description: "Show this shortcuts reference" },
  { keys: "Esc", description: "Close the open dialog, sheet, or menu" },
  { keys: "↑ / ↓", description: "Search: move the active result" },
  { keys: "Enter", description: "Search: open the active result" },
  { keys: "j / k", description: "Approvals/Notifications: move focus down/up a row" },
  { keys: "Enter", description: "Approvals/Notifications: open the focused row" },
  { keys: "a", description: "Approvals: approve the focused row" },
  { keys: "x", description: "Approvals: reject the focused row" },
  { keys: "v", description: "Approvals: toggle split view" },
  { keys: "r", description: "Notifications: mark the focused row read" },
  { keys: "e", description: "Notifications: archive the focused row" },
  { keys: "Ctrl/Cmd + Z", description: "Workflow Designer: undo" },
  { keys: "Ctrl/Cmd + Shift + Z", description: "Workflow Designer: redo" },
  { keys: "Ctrl/Cmd + S", description: "Workflow Designer: save draft" },
  { keys: "Delete", description: "Workflow Designer: remove the selected stage" },
];

/** "?" opens a dialog listing every keyboard shortcut this app defines. */
export function KeyboardShortcutsDialog() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const isTyping = target?.tagName === "INPUT" || target?.tagName === "TEXTAREA";
      if (event.key === "?" && !isTyping) {
        event.preventDefault();
        setOpen(true);
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, []);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Keyboard shortcuts</DialogTitle>
          <DialogDescription>Every shortcut this app defines.</DialogDescription>
        </DialogHeader>
        <ul className="space-y-2">
          {SHORTCUTS.map((shortcut) => (
            <li key={shortcut.keys} className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">{shortcut.description}</span>
              <kbd className="rounded border bg-muted px-1.5 py-0.5 font-mono text-xs">
                {shortcut.keys}
              </kbd>
            </li>
          ))}
        </ul>
      </DialogContent>
    </Dialog>
  );
}
