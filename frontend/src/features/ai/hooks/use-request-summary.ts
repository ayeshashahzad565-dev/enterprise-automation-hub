"use client";

import { useQuery } from "@tanstack/react-query";

import { aiKeys } from "@/features/ai/query-keys";
import { aiService } from "@/services/ai-service";

export function useRequestSummary(requestId: string) {
  return useQuery({
    queryKey: aiKeys.requestSummary(requestId),
    queryFn: () => aiService.getRequestSummary(requestId),
    staleTime: 60_000,
  });
}
