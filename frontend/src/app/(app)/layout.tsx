import type { ReactNode } from "react";

import { AppShell } from "@/components/layout/app-shell";
import { CommandPalette } from "@/components/patterns/command-palette";
import { KeyboardShortcutsDialog } from "@/components/patterns/keyboard-shortcuts-dialog";

export default function AppGroupLayout({ children }: { children: ReactNode }) {
  return (
    <AppShell>
      {children}
      <CommandPalette />
      <KeyboardShortcutsDialog />
    </AppShell>
  );
}
