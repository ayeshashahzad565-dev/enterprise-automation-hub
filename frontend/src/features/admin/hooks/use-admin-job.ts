"use client";

import { useQuery } from "@tanstack/react-query";

import { adminKeys } from "@/features/admin/query-keys";
import { adminService } from "@/services/admin-service";

export function useAdminJob(id: string, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: adminKeys.job(id),
    queryFn: () => adminService.getJob(id),
    enabled: options?.enabled ?? Boolean(id),
  });
}
