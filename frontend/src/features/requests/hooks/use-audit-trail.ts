"use client";

import { useQuery } from "@tanstack/react-query";

import { requestKeys } from "@/features/requests/query-keys";
import { requestService } from "@/services/request-service";

export function useAuditTrail(requestId: string) {
  return useQuery({
    queryKey: requestKeys.auditTrail(requestId),
    queryFn: () => requestService.getAuditTrail(requestId),
    staleTime: 60_000,
  });
}
