"use client";

import { BarChart3, Building2, ListChecks, Mail, Settings, ShieldCheck, Users } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { type ReactNode, useEffect } from "react";

import { useCurrentUser } from "@/features/profile/hooks/use-current-user";
import { cn } from "@/lib/utils";
import { ROUTES } from "@/utils/constants";

const ADMIN_SUB_NAV = [
  { href: ROUTES.admin, label: "Dashboard", icon: BarChart3, exact: true },
  { href: ROUTES.adminUsers, label: "Users", icon: Users },
  { href: ROUTES.adminInvitations, label: "Invitations", icon: Mail },
  { href: ROUTES.adminRoles, label: "Roles & Permissions", icon: ShieldCheck },
  { href: ROUTES.adminDepartments, label: "Departments", icon: Building2 },
  { href: ROUTES.adminJobs, label: "Jobs", icon: ListChecks },
  { href: ROUTES.adminSettings, label: "Settings", icon: Settings },
];

/**
 * The Platform Administration workspace's own layout — the first nested
 * layout in this codebase. Every route under `/admin` is admin-only at
 * the API layer; this client-side guard exists purely for usability
 * (redirect away from a page that would otherwise 403 on every request),
 * never as the real enforcement point.
 */
export default function AdminLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { data: profile, isLoading } = useCurrentUser();

  useEffect(() => {
    if (!isLoading && profile && profile.role !== "admin") {
      router.replace(ROUTES.unauthorized);
    }
  }, [isLoading, profile, router]);

  if (isLoading || profile?.role !== "admin") {
    return null;
  }

  return (
    <div className="space-y-4">
      <nav className="flex flex-wrap gap-1 border-b pb-2">
        {ADMIN_SUB_NAV.map(({ href, label, icon: Icon, exact }) => {
          const active = exact ? pathname === href : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                active
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
              )}
            >
              <Icon className="size-4" />
              {label}
            </Link>
          );
        })}
      </nav>
      {children}
    </div>
  );
}
