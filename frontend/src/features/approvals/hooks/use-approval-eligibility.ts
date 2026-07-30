"use client";

import { useQuery } from "@tanstack/react-query";

import { approvalKeys } from "@/features/approvals/query-keys";
import { approvalService } from "@/services/approval-service";

export function useApprovalEligibility(requestId: string, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: approvalKeys.eligibility(requestId),
    queryFn: () => approvalService.getEligibility(requestId),
    staleTime: 30_000,
    enabled: options?.enabled ?? true,
  });
}
