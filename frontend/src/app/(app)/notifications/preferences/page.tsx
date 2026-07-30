"use client";

import { useState } from "react";

import { ErrorState } from "@/components/patterns/error-state";
import { PageHeader } from "@/components/patterns/page-header";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { NotificationPreferencesList } from "@/features/notifications/components/notification-preferences-list";
import { useNotificationPreferences } from "@/features/notifications/hooks/use-notification-preferences";
import { useUpdateNotificationPreference } from "@/features/notifications/hooks/use-update-notification-preference";
import { notifyError } from "@/lib/toast";
import type { NotificationType } from "@/types/notification";

function PreferencesSkeleton() {
  return (
    <Card size="sm">
      <CardContent className="space-y-3">
        {Array.from({ length: 6 }).map((_, index) => (
          <Skeleton key={index} className="h-10 w-full" />
        ))}
      </CardContent>
    </Card>
  );
}

export default function NotificationPreferencesPage() {
  const { data: preferences, isLoading, isError, refetch } = useNotificationPreferences();
  const updatePreference = useUpdateNotificationPreference();
  const [pendingKey, setPendingKey] = useState<string | null>(null);

  async function handleToggle(
    notificationType: NotificationType,
    field: "in_app_enabled" | "email_enabled",
    value: boolean,
  ) {
    setPendingKey(notificationType);
    try {
      await updatePreference.mutateAsync({
        notificationType,
        body: { [field]: value },
      });
    } catch (error) {
      notifyError(error, "Couldn't update your notification preference.");
    } finally {
      setPendingKey(null);
    }
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="Notification preferences"
        description="Choose which events you're notified about, and how."
      />

      {isLoading ? (
        <PreferencesSkeleton />
      ) : isError || !preferences ? (
        <ErrorState message="Couldn't load your notification preferences." onRetry={() => refetch()} />
      ) : (
        <NotificationPreferencesList
          preferences={preferences}
          pendingKey={pendingKey}
          onToggle={handleToggle}
        />
      )}
    </div>
  );
}
