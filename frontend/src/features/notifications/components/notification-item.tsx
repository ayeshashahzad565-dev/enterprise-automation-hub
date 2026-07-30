"use client";

import { Archive, ArchiveRestore } from "lucide-react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { NotificationIcon } from "@/features/notifications/components/notification-icon";
import { formatRelativeTime } from "@/lib/format-relative-time";
import { cn } from "@/lib/utils";
import type { Notification } from "@/types/notification";
import { ROUTES } from "@/utils/constants";

/** Shared row renderer used by both the header dropdown and the full Notifications page. */
export function NotificationItem({
  notification,
  onMarkRead,
  onArchive,
  onUnarchive,
  focused = false,
  selected,
  onToggleSelected,
}: {
  notification: Notification;
  onMarkRead: (id: string) => void;
  onArchive?: (id: string) => void;
  onUnarchive?: (id: string) => void;
  focused?: boolean;
  selected?: boolean;
  onToggleSelected?: (id: string, checked: boolean) => void;
}) {
  const router = useRouter();

  function handleOpen() {
    if (!notification.is_read) onMarkRead(notification.id);
    if (notification.request_id) router.push(ROUTES.request(notification.request_id));
  }

  return (
    <div
      className={cn(
        "flex items-start gap-3 rounded-md px-3 py-2 text-sm transition-colors",
        notification.request_id && "cursor-pointer hover:bg-accent",
        focused && "bg-accent",
      )}
      onClick={notification.request_id ? handleOpen : undefined}
    >
      {onToggleSelected && (
        <Checkbox
          className="mt-1"
          checked={Boolean(selected)}
          onClick={(event) => event.stopPropagation()}
          onCheckedChange={(checked) => onToggleSelected(notification.id, checked === true)}
          aria-label="Select notification"
        />
      )}
      <NotificationIcon
        type={notification.notification_type}
        className={cn("mt-0.5 size-4 shrink-0", notification.is_read ? "text-muted-foreground" : "text-primary")}
      />
      <div className="min-w-0 flex-1 space-y-0.5">
        <p className={cn("truncate", !notification.is_read && "font-medium")}>{notification.message}</p>
        <p className="text-xs text-muted-foreground">{formatRelativeTime(notification.created_at)}</p>
      </div>
      {!notification.is_read && <span className="mt-2 size-2 shrink-0 rounded-full bg-primary" aria-hidden />}
      {onArchive && !notification.is_archived && (
        <Button
          variant="ghost"
          size="icon"
          className="size-7 shrink-0"
          aria-label="Archive"
          onClick={(event) => {
            event.stopPropagation();
            onArchive(notification.id);
          }}
        >
          <Archive className="size-4" />
        </Button>
      )}
      {onUnarchive && notification.is_archived && (
        <Button
          variant="ghost"
          size="icon"
          className="size-7 shrink-0"
          aria-label="Restore"
          onClick={(event) => {
            event.stopPropagation();
            onUnarchive(notification.id);
          }}
        >
          <ArchiveRestore className="size-4" />
        </Button>
      )}
    </div>
  );
}
