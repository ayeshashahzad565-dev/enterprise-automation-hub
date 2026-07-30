"use client";

import { useQuery } from "@tanstack/react-query";

import { adminKeys } from "@/features/admin/query-keys";
import { adminService } from "@/services/admin-service";
import type { UserRole } from "@/types/profile";

/** Mirrors the workflow-definitions list/search one-or-other pattern:
 * browsing by role and free-text name search are mutually exclusive,
 * since `ProfileRepository` exposes them as two separate methods
 * (`list_by_role`, `search_by_name`) with no combined query. */
export function useAdminUsers({
  role,
  query,
  page = 1,
  pageSize = 20,
}: {
  role: UserRole;
  query?: string;
  page?: number;
  pageSize?: number;
}) {
  const trimmedQuery = query?.trim();
  return useQuery({
    queryKey: trimmedQuery
      ? adminKeys.usersSearch(trimmedQuery, page, pageSize)
      : adminKeys.usersByRole(role, page, pageSize),
    queryFn: () =>
      trimmedQuery
        ? adminService.searchUsers(trimmedQuery, page, pageSize)
        : adminService.listUsersByRole(role, page, pageSize),
    staleTime: 30_000,
  });
}
