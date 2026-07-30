"use client";

import { useQuery } from "@tanstack/react-query";

import { aiKeys } from "@/features/ai/query-keys";
import { aiService } from "@/services/ai-service";

/** Named distinctly from `features/analytics/hooks/use-executive-summary.ts`
 * (the existing, non-AI, template-based summary) so both can coexist. */
export function useAiExecutiveSummary() {
  return useQuery({
    queryKey: aiKeys.executiveSummary(),
    queryFn: () => aiService.getExecutiveSummary(),
    staleTime: 300_000,
  });
}
