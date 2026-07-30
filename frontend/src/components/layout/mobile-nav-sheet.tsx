"use client";

import { Menu } from "lucide-react";
import { useState } from "react";

import { getNavGroups } from "@/components/layout/nav-items";
import { NavLinks } from "@/components/layout/nav-links";
import { SidebarBrand } from "@/components/layout/sidebar-brand";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { useCurrentUser } from "@/features/profile/hooks/use-current-user";

/**
 * The mobile navigation drawer — previously, every nav destination
 * became completely unreachable below the `md` breakpoint (the desktop
 * `Sidebar` is `hidden md:block` with no replacement). This reuses the
 * exact same nav data/gating as `Sidebar` via `getNavGroups`/`NavLinks`
 * — no new destinations, just making existing navigation reachable on
 * small screens.
 */
export function MobileNavSheet() {
  const [open, setOpen] = useState(false);
  const { data: profile } = useCurrentUser();

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger
        render={<Button variant="ghost" size="icon" className="md:hidden" aria-label="Open navigation" />}
      >
        <Menu className="size-5" />
      </SheetTrigger>
      <SheetContent side="left" className="w-64 gap-0 p-0">
        <SheetTitle className="sr-only">Navigation</SheetTitle>
        <SidebarBrand />
        <NavLinks
          groups={getNavGroups(profile?.role, profile?.is_platform_admin)}
          onNavigate={() => setOpen(false)}
        />
      </SheetContent>
    </Sheet>
  );
}
