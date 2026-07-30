/** Centralized TanStack Query key factory for the AI insights feature. */
export const aiKeys = {
  all: ["ai"] as const,
  requestSummary: (requestId: string) => [...aiKeys.all, "request-summary", requestId] as const,
  approvalSummary: (requestId: string) => [...aiKeys.all, "approval-summary", requestId] as const,
  workflowImprovements: (requestType: string) =>
    [...aiKeys.all, "workflow-improvements", requestType] as const,
  bottlenecks: () => [...aiKeys.all, "bottlenecks"] as const,
  policyRecommendations: () => [...aiKeys.all, "policy-recommendations"] as const,
  operationalInsights: () => [...aiKeys.all, "operational-insights"] as const,
  executiveSummary: () => [...aiKeys.all, "executive-summary"] as const,
};
