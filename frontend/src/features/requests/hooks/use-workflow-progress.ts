"use client";

import { useQuery } from "@tanstack/react-query";

import { requestKeys } from "@/features/requests/query-keys";
import { requestService } from "@/services/request-service";

export function useWorkflowProgress(requestId: string) {
  return useQuery({
    queryKey: requestKeys.workflow(requestId),
    queryFn: () => requestService.getWorkflowProgress(requestId),
    staleTime: 60_000,
  });
}
