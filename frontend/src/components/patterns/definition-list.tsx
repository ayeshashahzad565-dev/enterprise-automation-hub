import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * A vertical list of label/value rows — the "metadata panel" pattern
 * previously reimplemented three separate ways (`RequestMetadataPanel`'s
 * local `Row`, `PlatformSettingsView`'s local `SettingRow`, and
 * `ProfileCard`'s inline `<p>` tags). One shared, divided-row visual
 * treatment for all of them.
 */
export function DefinitionList({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("text-sm", className)}>{children}</div>;
}

export function DefinitionRow({
  label,
  children,
  className,
}: {
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-center justify-between gap-4 border-b py-2 last:border-b-0", className)}>
      <span className="text-caption text-muted-foreground">{label}</span>
      <span className="text-right font-medium">{children}</span>
    </div>
  );
}
