"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { workflowDefinitionKeys } from "@/features/workflow-designer/query-keys";
import { workflowDefinitionService } from "@/services/workflow-definition-service";
import type { UpdateWorkflowDefinitionBody } from "@/types/workflow-definition";

interface UpdateDraftInput {
  id: string;
  requestType: string;
  body: UpdateWorkflowDefinitionBody;
}

/** Backs both the manual "Save draft" toolbar button and the debounced autosave hook — identical mutation, different caller. */
export function useUpdateWorkflowDraft() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, body }: UpdateDraftInput) => workflowDefinitionService.updateDraft(id, body),
    onSettled: (_data, _error, variables) => {
      queryClient.invalidateQueries({ queryKey: workflowDefinitionKeys.versions(variables.requestType) });
    },
  });
}
