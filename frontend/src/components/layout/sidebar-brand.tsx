import { cn } from "@/lib/utils";

/** The sidebar/nav-drawer branding block — shared by the desktop `Sidebar`
 * and `MobileNavSheet` so both surfaces render identically. Sized to ~96px
 * with the wordmark centered vertically rather than pinned to the top edge,
 * with its own divider below (not the nav's), so the brand area reads as a
 * distinct zone from navigation. */
export function SidebarBrand({ className }: { className?: string }) {
  return (
    <div className={cn("flex h-24 items-center gap-2.5 border-b border-sidebar-border px-5", className)}>
      <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-sidebar-primary text-xs font-bold text-sidebar-primary-foreground">
        A
      </span>
      <div className="flex flex-col gap-1">
        <span className="text-lg font-bold tracking-tight text-sidebar-foreground">Automata</span>
        <span className="text-xs text-sidebar-foreground/60">Enterprise Automation Hub</span>
      </div>
    </div>
  );
}
