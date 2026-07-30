"use client";

import { useQuery } from "@tanstack/react-query";

import { aiKeys } from "@/features/ai/query-keys";
import { aiService } from "@/services/ai-service";

export function useWorkflowImprovements(requestType: string) {
  return useQuery({
    queryKey: aiKeys.workflowImprovements(requestType),
    queryFn: () => aiService.getWorkflowImprovements(requestType),
    staleTime: 300_000,
  });
}
