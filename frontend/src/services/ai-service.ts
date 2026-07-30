import { apiClient } from "@/lib/api/client";
import type { AiInsight, AskAssistantBody } from "@/types/ai";

export const aiService = {
  getRequestSummary: (requestId: string) =>
    apiClient.get<AiInsight>(`/ai/requests/${requestId}/summary`),
  getApprovalSummary: (requestId: string) =>
    apiClient.get<AiInsight>(`/ai/requests/${requestId}/approval-summary`),
  getWorkflowImprovements: (requestType: string) =>
    apiClient.get<AiInsight>(`/ai/workflows/${encodeURIComponent(requestType)}/improvements`),
  getBottleneckExplanation: () => apiClient.get<AiInsight>("/ai/operations/bottlenecks"),
  getPolicyRecommendations: () =>
    apiClient.get<AiInsight>("/ai/operations/policy-recommendations"),
  getOperationalInsights: () => apiClient.get<AiInsight>("/ai/operations/insights"),
  getExecutiveSummary: () => apiClient.get<AiInsight>("/ai/operations/executive-summary"),
  askAssistant: (body: AskAssistantBody) =>
    apiClient.post<AiInsight>("/ai/assistant/ask", body),
};
