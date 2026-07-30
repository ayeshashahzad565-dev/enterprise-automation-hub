"use client";

import { useQuery } from "@tanstack/react-query";

import { adminKeys } from "@/features/admin/query-keys";
import { adminService } from "@/services/admin-service";

export function useRoles() {
  return useQuery({
    queryKey: adminKeys.roles(),
    // The fixed, code-defined role/permission matrix rarely changes — a
    // long staleTime avoids refetching it on every navigation.
    queryFn: () => adminService.listRoles(),
    staleTime: 5 * 60_000,
  });
}
