"use client";

import { Bell, CheckCheck, Settings } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { DataTablePagination } from "@/components/patterns/data-table/data-table-pagination";
import { DayGroupedList } from "@/components/patterns/day-grouped-list";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { PageHeader } from "@/components/patterns/page-header";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ROUTES } from "@/utils/constants";
import { useArchiveNotification } from "@/features/notifications/hooks/use-archive-notification";
import { useMarkAllRead } from "@/features/notifications/hooks/use-mark-all-read";
import { useMarkRead } from "@/features/notifications/hooks/use-mark-read";
import { useNotificationKeyboardNav } from "@/features/notifications/hooks/use-notification-keyboard-nav";
import { useNotifications } from "@/features/notifications/hooks/use-notifications";
import { useUnarchiveNotification } from "@/features/notifications/hooks/use-unarchive-notification";
import { NotificationItem } from "@/features/notifications/components/notification-item";
import {
  EMPTY_NOTIFICATION_FILTERS,
  NotificationFiltersBar,
  type NotificationFilterState,
} from "@/features/notifications/components/notification-filters-bar";
import { notifyError, notifySuccess } from "@/lib/toast";
import type { NotificationListFilters } from "@/types/notification";

const SEARCH_DEBOUNCE_MS = 300;

export default function NotificationsPage() {
  const [filters, setFilters] = useState<NotificationFilterState>(EMPTY_NOTIFICATION_FILTERS);
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [focusedIndex, setFocusedIndex] = useState(-1);

  useEffect(() => {
    const timeout = setTimeout(() => {
      setDebouncedSearch(filters.search.trim());
      setPage(1);
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timeout);
  }, [filters.search]);

  const apiFilters = useMemo<NotificationListFilters>(
    () => ({
      is_read: filters.status === "all" ? undefined : filters.status === "read",
      notification_type: filters.notificationType || undefined,
      is_archived: filters.archived,
      search: debouncedSearch || undefined,
      page,
      page_size: pageSize,
    }),
    [filters.status, filters.notificationType, filters.archived, debouncedSearch, page, pageSize],
  );

  const { data, isLoading, isError, refetch } = useNotifications(apiFilters);
  const markRead = useMarkRead();
  const markAllRead = useMarkAllRead();
  const archive = useArchiveNotification();
  const unarchive = useUnarchiveNotification();

  const notifications = data?.data ?? [];

  useNotificationKeyboardNav({
    rowCount: notifications.length,
    focusedIndex,
    onFocusChange: setFocusedIndex,
    onOpen: (index) => {
      const notification = notifications[index];
      if (notification && !notification.is_read) markRead.mutate(notification.id);
    },
    onMarkRead: (index) => {
      const notification = notifications[index];
      if (notification && !notification.is_read) markRead.mutate(notification.id);
    },
    onArchive: (index) => {
      const notification = notifications[index];
      if (!notification) return;
      if (filters.archived) unarchive.mutate(notification.id);
      else archive.mutate(notification.id);
    },
  });

  async function handleMarkAllRead() {
    try {
      const result = await markAllRead.mutateAsync();
      notifySuccess(`${result.updated} marked as read.`);
    } catch (error) {
      notifyError(error, "Couldn't mark all as read.");
    }
  }

  async function handleBulkAction(action: "read" | "archive") {
    let succeeded = 0;
    let failed = 0;
    for (const id of selected) {
      try {
        if (action === "read") await markRead.mutateAsync(id);
        else if (filters.archived) await unarchive.mutateAsync(id);
        else await archive.mutateAsync(id);
        succeeded += 1;
      } catch {
        failed += 1;
      }
    }
    setSelected(new Set());
    const label = action === "read" ? "marked as read" : filters.archived ? "restored" : "archived";
    if (failed === 0) {
      toast.success(`${succeeded} ${label}.`);
    } else {
      toast.error(`${succeeded} ${label}, ${failed} failed.`);
    }
  }

  const hasUnread = notifications.some((n) => !n.is_read);
  const hasActiveFilter = Boolean(filters.search || filters.notificationType || filters.status !== "all");

  return (
    <div className="space-y-4">
      <PageHeader
        title="Notifications"
        actions={
          <div className="flex items-center gap-2">
            {hasUnread && (
              <Button
                variant="outline"
                size="sm"
                onClick={handleMarkAllRead}
                disabled={markAllRead.isPending}
              >
                <CheckCheck className="size-4" />
                Mark all read
              </Button>
            )}
            <Button
              variant="outline"
              size="sm"
              render={<Link href={ROUTES.notificationPreferences} />}
            >
              <Settings className="size-4" />
              Preferences
            </Button>
          </div>
        }
      />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <NotificationFiltersBar
          value={filters}
          onChange={(next) => {
            setFilters(next);
            setPage(1);
          }}
        />
        {selected.size > 0 && (
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground">{selected.size} selected</span>
            <Button size="sm" variant="outline" onClick={() => handleBulkAction("read")}>
              Mark read
            </Button>
            <Button size="sm" variant="outline" onClick={() => handleBulkAction("archive")}>
              {filters.archived ? "Restore" : "Archive"}
            </Button>
          </div>
        )}
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-14 w-full" />
          ))}
        </div>
      ) : isError ? (
        <ErrorState message="Couldn't load notifications." onRetry={() => refetch()} />
      ) : notifications.length === 0 ? (
        <EmptyState
          icon={Bell}
          title={hasActiveFilter ? "No matching notifications" : "You're all caught up"}
          description={
            hasActiveFilter
              ? "Try a different filter."
              : filters.archived
                ? "No archived notifications."
                : "New notifications will show up here."
          }
        />
      ) : (
        <>
          <DayGroupedList
            items={notifications}
            getKey={(notification) => notification.id}
            getDate={(notification) => notification.created_at}
            renderItem={(notification) => {
              const index = notifications.indexOf(notification);
              return (
                <NotificationItem
                  notification={notification}
                  focused={index === focusedIndex}
                  selected={selected.has(notification.id)}
                  onToggleSelected={(id, checked) => {
                    setSelected((prev) => {
                      const next = new Set(prev);
                      if (checked) next.add(id);
                      else next.delete(id);
                      return next;
                    });
                  }}
                  onMarkRead={(id) => markRead.mutate(id)}
                  onArchive={!filters.archived ? (id) => archive.mutate(id) : undefined}
                  onUnarchive={filters.archived ? (id) => unarchive.mutate(id) : undefined}
                />
              );
            }}
          />
          <DataTablePagination
            page={data?.pagination.page ?? 1}
            pageSize={data?.pagination.page_size ?? pageSize}
            totalRecords={data?.pagination.total_records ?? 0}
            totalPages={data?.pagination.total_pages ?? 1}
            onPageChange={setPage}
            onPageSizeChange={(size) => {
              setPageSize(size);
              setPage(1);
            }}
          />
        </>
      )}
    </div>
  );
}
