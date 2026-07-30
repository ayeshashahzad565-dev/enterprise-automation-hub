/** Centralized TanStack Query key factory for the Workflow Designer feature. */
export const workflowDefinitionKeys = {
  all: ["workflow-definitions"] as const,
  versions: (requestType: string) => [...workflowDefinitionKeys.all, "versions", requestType] as const,
  search: (queryText: string) => [...workflowDefinitionKeys.all, "search", queryText] as const,
};
