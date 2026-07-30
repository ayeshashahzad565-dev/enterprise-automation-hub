"use client";

import { useQuery } from "@tanstack/react-query";

import { adminKeys } from "@/features/admin/query-keys";
import { adminService } from "@/services/admin-service";

export function useDepartments() {
  return useQuery({
    queryKey: adminKeys.departments(),
    queryFn: () => adminService.listDepartments(),
    staleTime: 30_000,
  });
}
