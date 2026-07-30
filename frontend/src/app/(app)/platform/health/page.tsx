"use client";

import { ErrorState } from "@/components/patterns/error-state";
import { PageHeader } from "@/components/patterns/page-header";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { HealthStatusCards } from "@/features/platform/components/health-status-cards";
import { usePlatformHealth } from "@/features/platform/hooks/use-platform-health";

function HealthSkeleton() {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {Array.from({ length: 4 }).map((_, index) => (
        <Card key={index} size="sm">
          <CardContent className="space-y-2">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-6 w-20" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

export default function PlatformHealthPage() {
  const { data: health, isLoading, isError, refetch } = usePlatformHealth();

  return (
    <div className="space-y-4">
      <PageHeader
        breadcrumbs={[{ label: "Platform", href: "/platform" }, { label: "Health" }]}
        title="Platform health"
        description="Database, Redis, scheduler, and job-queue reachability, refreshed automatically."
      />

      {isLoading ? (
        <HealthSkeleton />
      ) : isError || !health ? (
        <ErrorState message="Couldn't load platform health." onRetry={() => refetch()} />
      ) : (
        <HealthStatusCards health={health} />
      )}
    </div>
  );
}
