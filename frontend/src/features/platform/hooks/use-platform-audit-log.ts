"use client";

import { useQuery } from "@tanstack/react-query";

import { platformKeys } from "@/features/platform/query-keys";
import { platformService } from "@/services/platform-service";
import type { PlatformAuditLogFilters } from "@/types/platform";

export function usePlatformAuditLog(filters: PlatformAuditLogFilters) {
  return useQuery({
    queryKey: platformKeys.auditLogList(filters),
    queryFn: () => platformService.listAuditLog(filters),
    staleTime: 15_000,
  });
}
