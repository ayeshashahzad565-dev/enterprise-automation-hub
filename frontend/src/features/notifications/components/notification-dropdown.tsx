"use client";

import { CheckCheck, Inbox, Settings } from "lucide-react";
import Link from "next/link";
import type { UIEvent } from "react";

import { Button } from "@/components/ui/button";
import { DropdownMenuContent, DropdownMenuLabel, DropdownMenuSeparator } from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { NotificationItem } from "@/features/notifications/components/notification-item";
import { useArchiveNotification } from "@/features/notifications/hooks/use-archive-notification";
import { useMarkAllRead } from "@/features/notifications/hooks/use-mark-all-read";
import { useMarkRead } from "@/features/notifications/hooks/use-mark-read";
import { useNotificationsInfinite } from "@/features/notifications/hooks/use-notifications-infinite";
import { notifyError, notifySuccess } from "@/lib/toast";
import { ROUTES } from "@/utils/constants";

/** Fetches the next page once the scrollable list is within this many
 * pixels of its bottom edge. */
const SCROLL_FETCH_THRESHOLD_PX = 48;

export function NotificationDropdown({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { data, isLoading, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useNotificationsInfinite({}, { enabled: open });
  const markRead = useMarkRead();
  const markAllRead = useMarkAllRead();
  const archive = useArchiveNotification();

  const notifications = data?.pages.flatMap((page) => page.data) ?? [];
  const hasUnread = notifications.some((n) => !n.is_read);

  function handleScroll(event: UIEvent<HTMLDivElement>) {
    const el = event.currentTarget;
    const nearBottom =
      el.scrollHeight - el.scrollTop - el.clientHeight < SCROLL_FETCH_THRESHOLD_PX;
    if (nearBottom && hasNextPage && !isFetchingNextPage) {
      fetchNextPage();
    }
  }

  async function handleMarkAllRead() {
    try {
      const result = await markAllRead.mutateAsync();
      notifySuccess(`${result.updated} marked as read.`);
    } catch (error) {
      notifyError(error, "Couldn't mark all as read.");
    }
  }

  return (
    <DropdownMenuContent align="end" className="w-80">
      <div className="flex items-center justify-between px-1.5 py-1">
        <DropdownMenuLabel className="p-0">Notifications</DropdownMenuLabel>
        {hasUnread && (
          <Button
            variant="ghost"
            size="sm"
            className="h-7 gap-1 text-xs"
            disabled={markAllRead.isPending}
            onClick={handleMarkAllRead}
          >
            <CheckCheck className="size-3.5" />
            Mark all read
          </Button>
        )}
      </div>
      <DropdownMenuSeparator />
      {isLoading ? (
        <div className="space-y-2 p-2">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : notifications.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-8 text-center">
          <Inbox className="size-6 text-muted-foreground" aria-hidden />
          <p className="text-sm text-muted-foreground">You&apos;re all caught up.</p>
        </div>
      ) : (
        <div className="max-h-96 space-y-0.5 overflow-y-auto" onScroll={handleScroll}>
          {notifications.map((notification) => (
            <NotificationItem
              key={notification.id}
              notification={notification}
              onMarkRead={(id) => markRead.mutate(id)}
              onArchive={(id) => archive.mutate(id)}
            />
          ))}
          {isFetchingNextPage && (
            <div className="space-y-2 p-2">
              <Skeleton className="h-10 w-full" />
            </div>
          )}
        </div>
      )}
      <DropdownMenuSeparator />
      <div className="flex items-center gap-1">
        <Link
          href={ROUTES.notifications}
          className="flex-1 rounded-md px-2 py-1.5 text-center text-sm hover:bg-accent"
          onClick={onClose}
        >
          View all
        </Link>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Notification preferences"
          render={<Link href={ROUTES.notificationPreferences} onClick={onClose} />}
        >
          <Settings className="size-4" />
        </Button>
      </div>
    </DropdownMenuContent>
  );
}
