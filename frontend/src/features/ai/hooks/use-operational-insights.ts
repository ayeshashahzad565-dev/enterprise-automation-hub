"use client";

import { useQuery } from "@tanstack/react-query";

import { aiKeys } from "@/features/ai/query-keys";
import { aiService } from "@/services/ai-service";

export function useOperationalInsights() {
  return useQuery({
    queryKey: aiKeys.operationalInsights(),
    queryFn: () => aiService.getOperationalInsights(),
    staleTime: 300_000,
  });
}
