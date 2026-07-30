"use client";

import { Building2 } from "lucide-react";

import { Caption } from "@/components/patterns/typography";
import { Card, CardContent } from "@/components/ui/card";
import type { DepartmentSummary } from "@/types/admin";

/** Departments are composed from users' free-text `department` field —
 * see `app.api.routers.admin_shared`'s docstring — not a formal backend
 * entity, so this is a grid of computed summaries, not a CRUD list. */
export function DepartmentList({
  departments,
  onSelect,
}: {
  departments: DepartmentSummary[];
  onSelect: (department: string) => void;
}) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {departments.map((department) => (
        <button
          key={department.department}
          type="button"
          onClick={() => onSelect(department.department)}
          className="text-left"
        >
          <Card size="sm" className="transition-all hover:-translate-y-0.5 hover:shadow-md hover:ring-primary/50">
            <CardContent className="space-y-2">
              <div className="flex items-center gap-2">
                <Building2 className="size-4 text-muted-foreground" aria-hidden />
                <p className="font-medium">{department.department}</p>
              </div>
              <Caption>
                {department.member_count} member{department.member_count === 1 ? "" : "s"}
              </Caption>
              <div className="flex gap-3 text-xs text-muted-foreground">
                <span>{department.roles.employee} employee</span>
                <span>{department.roles.approver} approver</span>
                <span>{department.roles.admin} admin</span>
              </div>
            </CardContent>
          </Card>
        </button>
      ))}
    </div>
  );
}
