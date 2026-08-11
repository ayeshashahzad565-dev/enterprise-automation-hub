import { apiClient } from "@/lib/api/client";
import type {
  CreateWorkflowDefinitionBody,
  UpdateWorkflowDefinitionBody,
  WorkflowDefinition,
} from "@/types/workflow-definition";

function buildQuery(params: object): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

export const workflowDefinitionService = {
  listVersions: (requestType: string) =>
    apiClient.getList<WorkflowDefinition>(
      `/workflow-definitions${buildQuery({ request_type: requestType })}`,
    ),
  search: (queryText: string) =>
    apiClient.getList<WorkflowDefinition>(
      `/workflow-definitions${buildQuery({ query_text: queryText })}`,
    ),
  create: (body: CreateWorkflowDefinitionBody) =>
    apiClient.post<WorkflowDefinition>("/workflow-definitions", body),
  updateDraft: (id: string, body: UpdateWorkflowDefinitionBody) =>
    apiClient.patch<WorkflowDefinition>(`/workflow-definitions/${id}`, body),
  activate: (id: string) =>
    apiClient.post<WorkflowDefinition>(`/workflow-definitions/${id}/activate`),
  deleteDraft: (id: string) => apiClient.delete<void>(`/workflow-definitions/${id}`),
};
