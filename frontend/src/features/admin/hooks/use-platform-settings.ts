"use client";

import { useQuery } from "@tanstack/react-query";

import { adminKeys } from "@/features/admin/query-keys";
import { adminService } from "@/services/admin-service";

export function usePlatformSettings() {
  return useQuery({
    queryKey: adminKeys.settings(),
    queryFn: () => adminService.getSettings(),
    staleTime: 5 * 60_000,
  });
}
