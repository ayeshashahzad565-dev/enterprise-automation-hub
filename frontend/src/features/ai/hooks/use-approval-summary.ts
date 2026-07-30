"use client";

import { useQuery } from "@tanstack/react-query";

import { aiKeys } from "@/features/ai/query-keys";
import { aiService } from "@/services/ai-service";

export function useApprovalSummary(requestId: string) {
  return useQuery({
    queryKey: aiKeys.approvalSummary(requestId),
    queryFn: () => aiService.getApprovalSummary(requestId),
    staleTime: 60_000,
  });
}
