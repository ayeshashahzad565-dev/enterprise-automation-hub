"use client";

import { useQuery } from "@tanstack/react-query";

import { aiKeys } from "@/features/ai/query-keys";
import { aiService } from "@/services/ai-service";

export function usePolicyRecommendations() {
  return useQuery({
    queryKey: aiKeys.policyRecommendations(),
    queryFn: () => aiService.getPolicyRecommendations(),
    staleTime: 300_000,
  });
}
