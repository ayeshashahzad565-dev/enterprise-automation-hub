"use client";

import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import type { UserRole } from "@/types/profile";

const ROLE_TABS: ReadonlyArray<{ value: UserRole; label: string }> = [
  { value: "employee", label: "Employees" },
  { value: "approver", label: "Approvers" },
  { value: "admin", label: "Admins" },
];

/** Mirrors the workflow-definitions list/search one-or-other pattern:
 * browsing by role and free-text name search are mutually exclusive,
 * since `ProfileRepository` exposes them as two separate methods with no
 * combined query. Typing a search term disables the role chips rather
 * than trying to combine both. */
export function UserDirectoryToolbar({
  role,
  query,
  onRoleChange,
  onQueryChange,
}: {
  role: UserRole;
  query: string;
  onRoleChange: (role: UserRole) => void;
  onQueryChange: (query: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className={query ? "pointer-events-none flex gap-1 opacity-50" : "flex gap-1"}>
        {ROLE_TABS.map((tab) => (
          <Button
            key={tab.value}
            type="button"
            size="sm"
            variant={role === tab.value ? "default" : "outline"}
            onClick={() => onRoleChange(tab.value)}
          >
            {tab.label}
          </Button>
        ))}
      </div>
      <Input
        value={query}
        onChange={(event) => onQueryChange(event.target.value)}
        placeholder="Search by name..."
        className="max-w-xs"
      />
    </div>
  );
}
