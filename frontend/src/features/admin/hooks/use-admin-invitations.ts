"use client";

import { useQuery } from "@tanstack/react-query";

import { adminKeys } from "@/features/admin/query-keys";
import { adminService } from "@/services/admin-service";
import type { InvitationStatus } from "@/types/admin";

/** How often the invitation list silently re-fetches while this page is
 * open, per the milestone's explicit request — an admin watching this
 * list benefits from seeing a just-accepted or newly-expired invitation
 * without a manual refresh. Uses TanStack Query's own `refetchInterval`
 * (no hand-rolled polling loop); `refetchIntervalInBackground` is left
 * at its default `false`, so polling pauses automatically once the tab
 * loses focus, matching "while the page is open." */
const AUTO_REFRESH_INTERVAL_MS = 45_000;

export function useAdminInvitations({
  status,
  query,
  page = 1,
  pageSize = 20,
}: {
  status?: InvitationStatus;
  query?: string;
  page?: number;
  pageSize?: number;
}) {
  const trimmedQuery = query?.trim() || undefined;
  return useQuery({
    queryKey: adminKeys.invitationsList({ status, query: trimmedQuery, page, pageSize }),
    queryFn: () =>
      adminService.listInvitations({ status, query: trimmedQuery, page, pageSize }),
    staleTime: 15_000,
    refetchInterval: AUTO_REFRESH_INTERVAL_MS,
  });
}
