"use client";

import { KpiRowSkeleton } from "@/components/patterns/charts/kpi-card";
import { ErrorState } from "@/components/patterns/error-state";
import { PageHeader } from "@/components/patterns/page-header";
import { AdminDashboardMetrics } from "@/features/admin/components/admin-dashboard-metrics";
import { useAdminDashboard } from "@/features/admin/hooks/use-admin-dashboard";

export default function AdminDashboardPage() {
  const { data, isLoading, isError, refetch } = useAdminDashboard();

  return (
    <div className="space-y-4">
      <PageHeader
        title="Administration"
        description="The operational control center for administrators."
      />

      {isLoading ? (
        <KpiRowSkeleton count={4} />
      ) : isError || !data ? (
        <ErrorState message="Couldn't load the administration dashboard." onRetry={() => refetch()} />
      ) : (
        <AdminDashboardMetrics dashboard={data} />
      )}
    </div>
  );
}
