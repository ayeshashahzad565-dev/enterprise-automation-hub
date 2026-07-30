"use client";

import { Flag, Plus } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { PageHeader } from "@/components/patterns/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { CreateFeatureFlagDialog } from "@/features/platform/components/create-feature-flag-dialog";
import { FeatureFlagsTable } from "@/features/platform/components/feature-flags-table";
import { useFeatureFlags } from "@/features/platform/hooks/use-feature-flags";
import { useUpdateFeatureFlag } from "@/features/platform/hooks/use-update-feature-flag";
import { notifyError } from "@/lib/toast";

function FeatureFlagsSkeleton() {
  return (
    <Card size="sm">
      <CardContent className="space-y-3">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-10 w-full" />
        ))}
      </CardContent>
    </Card>
  );
}

export default function PlatformFeatureFlagsPage() {
  const { data: flags, isLoading, isError, refetch } = useFeatureFlags();
  const updateFlag = useUpdateFeatureFlag();
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  async function handleToggle(key: string, enabled: boolean) {
    setPendingKey(key);
    try {
      await updateFlag.mutateAsync({ key, body: { enabled } });
    } catch (error) {
      notifyError(error, "Couldn't update this feature flag.");
    } finally {
      setPendingKey(null);
    }
  }

  return (
    <div className="space-y-4">
      <PageHeader
        breadcrumbs={[{ label: "Platform", href: "/platform" }, { label: "Feature flags" }]}
        title="Feature flags"
        description="Global, platform-admin-managed flags — informational only in this baseline; nothing in the app enforces them yet."
        actions={
          <Button size="sm" onClick={() => setCreateOpen(true)}>
            <Plus className="size-4" /> New flag
          </Button>
        }
      />

      {isLoading ? (
        <FeatureFlagsSkeleton />
      ) : isError || !flags ? (
        <ErrorState message="Couldn't load feature flags." onRetry={() => refetch()} />
      ) : flags.length === 0 ? (
        <EmptyState
          icon={Flag}
          title="No feature flags yet"
          description="Create one to start tracking a rollout."
        />
      ) : (
        <FeatureFlagsTable flags={flags} pendingKey={pendingKey} onToggle={handleToggle} />
      )}

      <CreateFeatureFlagDialog open={createOpen} onOpenChange={setCreateOpen} />
    </div>
  );
}
