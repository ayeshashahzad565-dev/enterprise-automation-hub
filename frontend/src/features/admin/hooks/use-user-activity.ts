"use client";

import { useQuery } from "@tanstack/react-query";

import { adminKeys } from "@/features/admin/query-keys";
import { adminService } from "@/services/admin-service";

export function useUserActivity(id: string, page = 1) {
  return useQuery({
    queryKey: adminKeys.userActivity(id, page),
    queryFn: () => adminService.getUserActivity(id, page),
    enabled: Boolean(id),
  });
}
