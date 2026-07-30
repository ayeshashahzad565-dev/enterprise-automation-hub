"use client";

import { useInfiniteQuery } from "@tanstack/react-query";

import { notificationKeys } from "@/features/notifications/query-keys";
import { notificationService } from "@/services/notification-service";
import type { NotificationListFilters } from "@/types/notification";

const DROPDOWN_PAGE_SIZE = 8;

/**
 * Powers the bell dropdown's scroll-to-load-more list — a separate query
 * key/shape from `useNotifications` (which the full `/notifications`
 * history page uses with classic `DataTablePagination`), since the two
 * surfaces page through the same `GET /notifications` endpoint
 * differently and must not share a cache entry.
 */
export function useNotificationsInfinite(
  filters: Omit<NotificationListFilters, "page" | "page_size">,
  options?: { enabled?: boolean },
) {
  return useInfiniteQuery({
    queryKey: notificationKeys.infiniteList(filters),
    queryFn: ({ pageParam }) =>
      notificationService.list({ ...filters, page: pageParam, page_size: DROPDOWN_PAGE_SIZE }),
    initialPageParam: 1,
    getNextPageParam: (lastPage) =>
      lastPage.pagination.page < lastPage.pagination.total_pages
        ? lastPage.pagination.page + 1
        : undefined,
    staleTime: 15_000,
    enabled: options?.enabled,
  });
}
