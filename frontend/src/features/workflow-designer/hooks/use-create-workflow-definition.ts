"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { workflowDefinitionKeys } from "@/features/workflow-designer/query-keys";
import { workflowDefinitionService } from "@/services/workflow-definition-service";
import type { CreateWorkflowDefinitionBody } from "@/types/workflow-definition";

/** Creating a new draft is infrequent and consequential — toast at the call-site, not inside this hook, matching the request-creation precedent rather than the toast-less notification mark-read precedent. */
export function useCreateWorkflowDefinition() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (body: CreateWorkflowDefinitionBody) => workflowDefinitionService.create(body),
    onSettled: (data, _error, variables) => {
      const requestType = data?.request_type ?? variables.request_type;
      queryClient.invalidateQueries({ queryKey: workflowDefinitionKeys.versions(requestType) });
    },
  });
}
