"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import type { NavItem } from "@/components/layout/nav-items";
import { cn } from "@/lib/utils";

/** Renders one or more role-gated nav groups (see `getNavGroups`) with a
 * subtle divider between tiers, so the hierarchy that already exists in
 * the data (base / approver+ / admin) is visible, not just structural.
 * Shared by the desktop `Sidebar` and the mobile `MobileNavSheet`. */
export function NavLinks({ groups, onNavigate }: { groups: NavItem[][]; onNavigate?: () => void }) {
  const pathname = usePathname();

  return (
    <nav className="space-y-1.5 p-3">
      {groups.map((items, groupIndex) => (
        <div key={groupIndex} className={cn(groupIndex > 0 && "mt-3 space-y-1.5 border-t border-sidebar-border pt-3")}>
          {items.map(({ href, label, icon: Icon }) => {
            const active = pathname === href || pathname.startsWith(`${href}/`);
            return (
              <Link
                key={href}
                href={href}
                onClick={onNavigate}
                className={cn(
                  "relative flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm font-medium transition-all duration-200",
                  active
                    ? "bg-sidebar-primary/10 text-sidebar-primary before:absolute before:inset-y-1.5 before:left-0 before:w-0.5 before:rounded-full before:bg-sidebar-primary"
                    : "text-sidebar-foreground/70 hover:translate-x-0.5 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
                )}
              >
                <Icon className="size-5 shrink-0" />
                {label}
              </Link>
            );
          })}
        </div>
      ))}
    </nav>
  );
}
