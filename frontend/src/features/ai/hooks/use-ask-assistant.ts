"use client";

import { useMutation } from "@tanstack/react-query";

import { aiService } from "@/services/ai-service";
import type { AskAssistantBody } from "@/types/ai";

/** Deliberately not cached/keyed via `useQuery` — an arbitrary question
 * plus per-call conversation history is not a stable, cacheable resource,
 * matching `AiInsightService.ask_assistant`'s own "not cached" design. */
export function useAskAssistant() {
  return useMutation({
    mutationFn: (body: AskAssistantBody) => aiService.askAssistant(body),
  });
}
