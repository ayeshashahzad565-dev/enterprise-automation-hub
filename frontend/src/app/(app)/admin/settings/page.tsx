"use client";

import { Card, CardContent } from "@/components/ui/card";
import { ErrorState } from "@/components/patterns/error-state";
import { PageHeader } from "@/components/patterns/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { PlatformSettingsView } from "@/features/admin/components/platform-settings-view";
import { usePlatformSettings } from "@/features/admin/hooks/use-platform-settings";

function SettingsSkeleton() {
  return (
    <div className="space-y-4">
      {Array.from({ length: 4 }).map((_, index) => (
        <Card key={index} size="sm">
          <CardContent className="space-y-2">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-full" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

export default function AdminSettingsPage() {
  const { data, isLoading, isError, refetch } = usePlatformSettings();

  return (
    <div className="space-y-4">
      <PageHeader
        title="Platform Settings"
        description="Read-only — only existing backend configuration is shown."
      />

      {isLoading ? (
        <SettingsSkeleton />
      ) : isError || !data ? (
        <ErrorState message="Couldn't load platform settings." onRetry={() => refetch()} />
      ) : (
        <PlatformSettingsView settings={data} />
      )}
    </div>
  );
}
