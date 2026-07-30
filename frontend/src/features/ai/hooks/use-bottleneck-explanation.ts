"use client";

import { useQuery } from "@tanstack/react-query";

import { aiKeys } from "@/features/ai/query-keys";
import { aiService } from "@/services/ai-service";

export function useBottleneckExplanation() {
  return useQuery({
    queryKey: aiKeys.bottlenecks(),
    queryFn: () => aiService.getBottleneckExplanation(),
    staleTime: 300_000,
  });
}
