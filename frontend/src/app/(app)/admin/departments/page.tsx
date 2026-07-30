"use client";

import { Building2 } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { PageHeader } from "@/components/patterns/page-header";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { DepartmentDetailPanel } from "@/features/admin/components/department-detail-panel";
import { DepartmentList } from "@/features/admin/components/department-list";
import { useDepartments } from "@/features/admin/hooks/use-departments";

function DepartmentListSkeleton() {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: 6 }).map((_, index) => (
        <Card key={index} size="sm">
          <CardContent className="space-y-2">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-3 w-16" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

export default function AdminDepartmentsPage() {
  const { data, isLoading, isError, refetch } = useDepartments();
  const [selectedDepartment, setSelectedDepartment] = useState<string | null>(null);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Departments"
        description="Composed from users' department field — not a formal backend entity."
      />

      {isLoading ? (
        <DepartmentListSkeleton />
      ) : isError || !data ? (
        <ErrorState message="Couldn't load departments." onRetry={() => refetch()} />
      ) : data.length === 0 ? (
        <EmptyState icon={Building2} title="No departments yet" description="No users have a department set." />
      ) : (
        <DepartmentList departments={data} onSelect={setSelectedDepartment} />
      )}

      <DepartmentDetailPanel
        department={selectedDepartment}
        open={selectedDepartment !== null}
        onOpenChange={(open) => !open && setSelectedDepartment(null)}
      />
    </div>
  );
}
