"use client";

import { getNavGroups } from "@/components/layout/nav-items";
import { NavLinks } from "@/components/layout/nav-links";
import { SidebarBrand } from "@/components/layout/sidebar-brand";
import { useCurrentUser } from "@/features/profile/hooks/use-current-user";

export function Sidebar() {
  const { data: profile } = useCurrentUser();

  return (
    <aside className="hidden w-64 shrink-0 border-r bg-sidebar md:block">
      <SidebarBrand />
      <NavLinks groups={getNavGroups(profile?.role, profile?.is_platform_admin)} />
    </aside>
  );
}
