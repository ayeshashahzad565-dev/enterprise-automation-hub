"use client";

import { useQuery } from "@tanstack/react-query";

import { adminKeys } from "@/features/admin/query-keys";
import { adminService } from "@/services/admin-service";

export function useAdminDashboard() {
  return useQuery({
    queryKey: adminKeys.dashboard(),
    queryFn: () => adminService.getDashboard(),
    staleTime: 30_000,
  });
}
