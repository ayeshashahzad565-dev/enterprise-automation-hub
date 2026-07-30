"use client";

import { DataTableSkeleton } from "@/components/patterns/data-table/data-table-skeleton";
import { ErrorState } from "@/components/patterns/error-state";
import { PageHeader } from "@/components/patterns/page-header";
import { PermissionMatrix } from "@/features/admin/components/permission-matrix";
import { useRoles } from "@/features/admin/hooks/use-roles";

export default function AdminRolesPage() {
  const { data, isLoading, isError, refetch } = useRoles();

  return (
    <div className="space-y-4">
      <PageHeader
        title="Roles & Permissions"
        description="A read-only view of exactly what the backend enforces for each role."
      />

      {isLoading ? (
        <DataTableSkeleton columnCount={4} rowCount={12} />
      ) : isError || !data ? (
        <ErrorState message="Couldn't load the permission matrix." onRetry={() => refetch()} />
      ) : (
        <PermissionMatrix roles={data} />
      )}
    </div>
  );
}
