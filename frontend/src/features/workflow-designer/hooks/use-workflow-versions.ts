"use client";

import { useQuery } from "@tanstack/react-query";

import { workflowDefinitionKeys } from "@/features/workflow-designer/query-keys";
import { workflowDefinitionService } from "@/services/workflow-definition-service";

export function useWorkflowVersions(requestType: string, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: workflowDefinitionKeys.versions(requestType),
    queryFn: () => workflowDefinitionService.listVersions(requestType),
    staleTime: 30_000,
    enabled: options?.enabled ?? Boolean(requestType),
  });
}
