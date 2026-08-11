"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { workflowDefinitionKeys } from "@/features/workflow-designer/query-keys";
import { workflowDefinitionService } from "@/services/workflow-definition-service";

interface DeleteDraftInput {
  id: string;
  requestType: string;
}

export function useDeleteWorkflowDraft() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id }: DeleteDraftInput) => workflowDefinitionService.deleteDraft(id),
    onSettled: (_data, _error, variables) => {
      queryClient.invalidateQueries({ queryKey: workflowDefinitionKeys.versions(variables.requestType) });
    },
  });
}
