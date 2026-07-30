import {
  Activity,
  BarChart3,
  Building2,
  CheckSquare,
  FileText,
  GitBranch,
  LayoutDashboard,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";

import type { UserRole } from "@/types/profile";
import { ROUTES } from "@/utils/constants";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

const BASE_NAV_ITEMS: NavItem[] = [
  { href: ROUTES.dashboard, label: "Dashboard", icon: LayoutDashboard },
  { href: ROUTES.requests, label: "Requests", icon: FileText },
  { href: ROUTES.activity, label: "Activity", icon: Activity },
];

const APPROVER_NAV_ITEMS: NavItem[] = [
  { href: ROUTES.approvals, label: "Approvals", icon: CheckSquare },
  { href: ROUTES.analytics, label: "Analytics", icon: BarChart3 },
];

// The admin-only nav tier — every route here 403s for every other role
// at the API layer, so (matching the Approvals/Analytics rationale
// below) the links are hidden rather than shown-then-403ing.
const ADMIN_NAV_ITEMS: NavItem[] = [
  { href: ROUTES.workflows, label: "Workflows", icon: GitBranch },
  { href: ROUTES.admin, label: "Admin", icon: ShieldCheck },
];

// Platform Administration is gated on `Profile.is_platform_admin`, not
// `role` — a platform admin might hold any company role, so this tier is
// orthogonal to (and independent of) `ADMIN_NAV_ITEMS` above.
const PLATFORM_NAV_ITEMS: NavItem[] = [
  { href: ROUTES.platform, label: "Platform", icon: Building2 },
];

/**
 * The app's navigation, grouped into role-gated tiers — shared by the
 * desktop `Sidebar` and the mobile `MobileNavSheet` so both surfaces
 * render identically and gate identically, from one source of truth.
 * Each returned group renders as its own visually-separated section.
 */
export function getNavGroups(role: UserRole | undefined, isPlatformAdmin?: boolean): NavItem[][] {
  const groups: NavItem[][] = [BASE_NAV_ITEMS];
  if (role !== "employee") {
    groups.push(APPROVER_NAV_ITEMS);
  }
  if (role === "admin") {
    groups.push(ADMIN_NAV_ITEMS);
  }
  if (isPlatformAdmin) {
    groups.push(PLATFORM_NAV_ITEMS);
  }
  return groups;
}
