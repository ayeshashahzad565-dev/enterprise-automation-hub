"use client";

import { useQuery } from "@tanstack/react-query";

import { workflowDefinitionKeys } from "@/features/workflow-designer/query-keys";
import { workflowDefinitionService } from "@/services/workflow-definition-service";

export function useWorkflowSearch(queryText: string) {
  return useQuery({
    queryKey: workflowDefinitionKeys.search(queryText),
    queryFn: () => workflowDefinitionService.search(queryText),
    staleTime: 30_000,
    enabled: queryText.trim().length > 0,
  });
}
