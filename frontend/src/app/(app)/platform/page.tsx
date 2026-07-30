"use client";

import { useMemo } from "react";

import { ErrorState } from "@/components/patterns/error-state";
import { PageHeader } from "@/components/patterns/page-header";
import { SectionHeading } from "@/components/patterns/typography";
import { KpiRow, KpiRowSkeleton } from "@/components/patterns/charts/kpi-card";
import { TrendChart } from "@/components/patterns/charts/trend-chart";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { HealthStatusCards } from "@/features/platform/components/health-status-cards";
import { PlatformActivityList } from "@/features/platform/components/platform-activity-list";
import { useCompanies } from "@/features/platform/hooks/use-companies";
import { usePlatformAuditLog } from "@/features/platform/hooks/use-platform-audit-log";
import { usePlatformHealth } from "@/features/platform/hooks/use-platform-health";
import { usePlatformStats } from "@/features/platform/hooks/use-platform-stats";
import { formatStorageBytes } from "@/features/platform/lib/format-bytes";

export default function PlatformOverviewPage() {
  const statsQuery = usePlatformStats();
  const healthQuery = usePlatformHealth();
  const activityQuery = usePlatformAuditLog({ page_size: 15 });
  const companiesQuery = useCompanies({ pageSize: 100 });

  const companyNamesById = useMemo(
    () => new Map((companiesQuery.data?.data ?? []).map((company) => [company.id, company.name])),
    [companiesQuery.data],
  );

  const stats = statsQuery.data;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Platform"
        description="Cross-tenant statistics, health, and activity — visible to platform admins only."
      />

      {statsQuery.isLoading ? (
        <KpiRowSkeleton count={5} />
      ) : statsQuery.isError || !stats ? (
        <ErrorState message="Couldn't load platform statistics." onRetry={() => statsQuery.refetch()} />
      ) : (
        <KpiRow
          items={[
            { label: "Active tenants", value: `${stats.active_tenants} / ${stats.total_tenants}` },
            { label: "Total users", value: stats.total_users.toLocaleString() },
            { label: "Total requests", value: stats.total_requests.toLocaleString() },
            { label: "Active workflows", value: stats.active_workflow_definitions.toLocaleString() },
            { label: "Storage used", value: formatStorageBytes(stats.total_storage_bytes) },
          ]}
        />
      )}

      <div className="space-y-2">
        <SectionHeading>Request volume (last 30 days)</SectionHeading>
        {statsQuery.isLoading ? (
          <Skeleton className="h-64 w-full" />
        ) : statsQuery.isError || !stats ? (
          <ErrorState message="Couldn't load the request-volume trend." onRetry={() => statsQuery.refetch()} />
        ) : stats.request_volume_trend.length === 0 ? (
          <Card size="sm">
            <CardContent>
              <p className="text-sm text-muted-foreground">No requests in this window.</p>
            </CardContent>
          </Card>
        ) : (
          <Card size="sm">
            <CardContent>
              <TrendChart points={stats.request_volume_trend} />
            </CardContent>
          </Card>
        )}
      </div>

      <div className="space-y-2">
        <SectionHeading>Health</SectionHeading>
        {healthQuery.isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : healthQuery.isError || !healthQuery.data ? (
          <ErrorState message="Couldn't load platform health." onRetry={() => healthQuery.refetch()} />
        ) : (
          <HealthStatusCards health={healthQuery.data} />
        )}
      </div>

      <div className="space-y-2">
        <SectionHeading>Recent activity</SectionHeading>
        {activityQuery.isLoading ? (
          <Skeleton className="h-48 w-full" />
        ) : activityQuery.isError ? (
          <ErrorState message="Couldn't load recent activity." onRetry={() => activityQuery.refetch()} />
        ) : (activityQuery.data?.data.length ?? 0) === 0 ? (
          <p className="text-sm text-muted-foreground">No recorded platform activity yet.</p>
        ) : (
          <Card size="sm">
            <CardContent>
              <PlatformActivityList
                entries={activityQuery.data?.data ?? []}
                companyNamesById={companyNamesById}
              />
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
