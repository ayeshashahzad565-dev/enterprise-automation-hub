"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { workflowDefinitionKeys } from "@/features/workflow-designer/query-keys";
import { workflowDefinitionService } from "@/services/workflow-definition-service";
import type { WorkflowDefinition } from "@/types/workflow-definition";

interface DuplicateInput {
  source: WorkflowDefinition;
  targetRequestType: string;
}

/**
 * "Duplicate" has no backend endpoint of its own — it composes the
 * existing create endpoint with a copy of an already-fetched version's
 * `stages` (list_versions/search already return the full definition
 * document inline), the same "zero new backend surface" class of reuse
 * as Phase 4's aging-requests enrichment.
 */
export function useDuplicateWorkflowDefinition() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ source, targetRequestType }: DuplicateInput) =>
      workflowDefinitionService.create({
        request_type: targetRequestType,
        definition: { stages: source.definition.stages.map((stage) => ({ ...stage })) },
      }),
    onSettled: (data, _error, variables) => {
      const requestType = data?.request_type ?? variables.targetRequestType;
      queryClient.invalidateQueries({ queryKey: workflowDefinitionKeys.versions(requestType) });
    },
  });
}
