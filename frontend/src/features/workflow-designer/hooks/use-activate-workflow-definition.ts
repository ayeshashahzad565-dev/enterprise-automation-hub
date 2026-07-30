"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { workflowDefinitionKeys } from "@/features/workflow-designer/query-keys";
import { workflowDefinitionService } from "@/services/workflow-definition-service";

interface ActivateInput {
  id: string;
  requestType: string;
}

/** Not optimistic: activation atomically flips a different version off server-side, so the whole version list is re-fetched from truth rather than guessed at locally. */
export function useActivateWorkflowDefinition() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id }: ActivateInput) => workflowDefinitionService.activate(id),
    onSettled: (_data, _error, variables) => {
      queryClient.invalidateQueries({ queryKey: workflowDefinitionKeys.versions(variables.requestType) });
    },
  });
}
