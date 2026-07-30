"use client";

import { Search } from "lucide-react";
import { useEffect, useState } from "react";

import { MobileNavSheet } from "@/components/layout/mobile-nav-sheet";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { UserMenu } from "@/components/layout/user-menu";
import { Button } from "@/components/ui/button";
import { NotificationBell } from "@/features/notifications/components/notification-bell";
import { OPEN_COMMAND_PALETTE_EVENT } from "@/utils/constants";

/** "⌘" renders as a missing-glyph box on the fonts most Windows/Linux
 * browsers fall back to, which is what the shortcut hint looked like
 * ("a weird icon") to most of this app's users — the palette itself
 * already accepts both metaKey and ctrlKey, so the label just needs to
 * match whichever key the user's platform actually has. Defaults to the
 * Windows/Linux label so there's no server/client render mismatch, and
 * swaps to the Mac label after mount once `navigator.platform` is known. */
function useShortcutLabel(): string {
  const [label, setLabel] = useState("Ctrl+K");
  useEffect(() => {
    if (/Mac|iPod|iPhone|iPad/.test(navigator.platform)) {
      setLabel("⌘K");
    }
  }, []);
  return label;
}

export function Header() {
  const shortcutLabel = useShortcutLabel();
  return (
    <header className="flex h-14 items-center gap-3 border-b px-4">
      <MobileNavSheet />
      <span className="font-bold md:hidden">Automata</span>
      <Button
        variant="outline"
        size="sm"
        className="hidden flex-1 justify-start gap-2 text-muted-foreground sm:flex"
        onClick={() => document.dispatchEvent(new Event(OPEN_COMMAND_PALETTE_EVENT))}
      >
        <Search className="size-5" />
        Search...
        <kbd className="ml-auto rounded border bg-muted px-1.5 py-0.5 font-mono text-[0.7rem]">
          {shortcutLabel}
        </kbd>
      </Button>
      <div className="ml-auto flex shrink-0 items-center gap-2">
        <NotificationBell />
        <ThemeToggle />
        <UserMenu />
      </div>
    </header>
  );
}
