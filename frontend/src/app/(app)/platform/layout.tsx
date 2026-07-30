"use client";

import { Activity, BarChart3, Building2, Flag, HeartPulse } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { type ReactNode, useEffect } from "react";

import { useCurrentUser } from "@/features/profile/hooks/use-current-user";
import { cn } from "@/lib/utils";
import { ROUTES } from "@/utils/constants";

const PLATFORM_SUB_NAV = [
  { href: ROUTES.platform, label: "Overview", icon: BarChart3, exact: true },
  { href: ROUTES.platformCompanies, label: "Companies", icon: Building2 },
  { href: ROUTES.platformAudit, label: "Audit", icon: Activity },
  { href: ROUTES.platformFeatureFlags, label: "Feature flags", icon: Flag },
  { href: ROUTES.platformHealth, label: "Health", icon: HeartPulse },
];

/**
 * The Platform Administration workspace's own layout — a sibling of
 * `/admin`, not nested under it: `is_platform_admin` is orthogonal to
 * `role` (see `Profile.is_platform_admin`'s own doc comment), so a
 * platform admin might not hold the company `admin` role at all. Every
 * route under `/platform` is platform-admin-only at the API layer; this
 * client-side guard exists purely for usability (redirect away from a
 * page that would otherwise 403 on every request), never as the real
 * enforcement point — mirrors `admin/layout.tsx`'s exact shape.
 */
export default function PlatformLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { data: profile, isLoading } = useCurrentUser();

  useEffect(() => {
    if (!isLoading && profile && !profile.is_platform_admin) {
      router.replace(ROUTES.unauthorized);
    }
  }, [isLoading, profile, router]);

  if (isLoading || !profile?.is_platform_admin) {
    return null;
  }

  return (
    <div className="space-y-4">
      <nav className="flex flex-wrap gap-1 border-b pb-2">
        {PLATFORM_SUB_NAV.map(({ href, label, icon: Icon, exact }) => {
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
