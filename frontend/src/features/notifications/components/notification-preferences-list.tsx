"use client";

import { NotificationIcon } from "@/features/notifications/components/notification-icon";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { NotificationPreference, NotificationType } from "@/types/notification";

const LABELS: Record<NotificationType, { title: string; description: string }> = {
  assignment: {
    title: "Assignment",
    description: "You're assigned to review a request.",
  },
  reminder: {
    title: "Reminder",
    description: "A stage you own is nearing its escalation deadline.",
  },
  escalation: {
    title: "Escalation",
    description: "A stage was escalated to you.",
  },
  decision: {
    title: "Decision",
    description: "A request you submitted was approved or rejected.",
  },
  completion: {
    title: "Completion",
    description: "A request you submitted has completed.",
  },
  system: {
    title: "System",
    description: "Platform announcements and maintenance notices.",
  },
};

export function NotificationPreferencesList({
  preferences,
  pendingKey,
  onToggle,
}: {
  preferences: NotificationPreference[];
  pendingKey: string | null;
  onToggle: (
    notificationType: NotificationType,
    field: "in_app_enabled" | "email_enabled",
    value: boolean,
  ) => void;
}) {
  return (
    <div className="overflow-hidden rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Event</TableHead>
            <TableHead>In-app</TableHead>
            <TableHead>Email</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {preferences.map((preference) => {
            const label = LABELS[preference.notification_type];
            const pending = pendingKey === preference.notification_type;
            return (
              <TableRow key={preference.notification_type}>
                <TableCell>
                  <div className="flex items-center gap-2">
                    <NotificationIcon
                      type={preference.notification_type}
                      className="size-4 text-muted-foreground"
                    />
                    <div>
                      <div className="font-medium">{label.title}</div>
                      <div className="text-sm text-muted-foreground">{label.description}</div>
                    </div>
                  </div>
                </TableCell>
                <TableCell>
                  <Switch
                    checked={preference.in_app_enabled}
                    disabled={pending}
                    onCheckedChange={(checked) =>
                      onToggle(preference.notification_type, "in_app_enabled", checked)
                    }
                    aria-label={`${preference.in_app_enabled ? "Disable" : "Enable"} in-app ${label.title} notifications`}
                  />
                </TableCell>
                <TableCell>
                  <Switch
                    checked={preference.email_enabled}
                    disabled={pending || !preference.in_app_enabled}
                    onCheckedChange={(checked) =>
                      onToggle(preference.notification_type, "email_enabled", checked)
                    }
                    aria-label={`${preference.email_enabled ? "Disable" : "Enable"} email ${label.title} notifications`}
                  />
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
