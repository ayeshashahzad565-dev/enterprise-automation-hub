"use client";

import { Caption, Metric, SectionHeading } from "@/components/patterns/typography";
import { Skeleton } from "@/components/ui/skeleton";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useDepartmentWorkload } from "@/features/admin/hooks/use-department-workload";

/** Member list plus request-volume workload, reusing the same
 * `AnalyticsProvider.get_department_metrics` call `DepartmentComparePanel`
 * already uses via the analytics router. */
export function DepartmentDetailPanel({
  department,
  open,
  onOpenChange,
}: {
  department: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { data, isLoading } = useDepartmentWorkload(department ?? "", {
    enabled: Boolean(department),
  });

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="flex w-full flex-col gap-4 overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>{department ?? "Department"}</SheetTitle>
        </SheetHeader>

        <div className="space-y-4 px-4 pb-4">
          {isLoading ? (
            <div className="space-y-4">
              <Skeleton className="h-8 w-16" />
              <Skeleton className="h-24 w-full" />
            </div>
          ) : data ? (
            <>
              <div>
                <Caption>Open request workload</Caption>
                <Metric>{data.workload}</Metric>
              </div>
              <div className="space-y-2">
                <SectionHeading>Members ({data.member_count})</SectionHeading>
                <ul className="space-y-1 text-sm">
                  {data.members.map((member) => (
                    <li key={member.id} className="flex items-center justify-between">
                      <span>{member.full_name}</span>
                      <span className="text-xs text-muted-foreground capitalize">
                        {member.role}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            </>
          ) : null}
        </div>
      </SheetContent>
    </Sheet>
  );
}
