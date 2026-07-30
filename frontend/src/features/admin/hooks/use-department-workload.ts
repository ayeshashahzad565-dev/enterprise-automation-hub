"use client";

import { useQuery } from "@tanstack/react-query";

import { adminKeys } from "@/features/admin/query-keys";
import { adminService } from "@/services/admin-service";

export function useDepartmentWorkload(department: string, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: adminKeys.departmentWorkload(department),
    queryFn: () => adminService.getDepartmentWorkload(department),
    enabled: options?.enabled ?? Boolean(department),
    staleTime: 30_000,
  });
}
