import { apiClient } from "@/lib/api/client";
import type {
  ApprovalEligibility,
  ApprovalInboxItem,
  ApprovalOutcome,
  BulkDecisionItem,
  BulkDecisionResult,
  DecisionInput,
} from "@/types/approval";

export interface ListInboxParams {
  page?: number;
  page_size?: number;
}

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

export const approvalService = {
  listInbox: (params: ListInboxParams = {}) =>
    apiClient.getList<ApprovalInboxItem>(`/approvals/inbox${buildQuery(params)}`),
  approve: (stageId: string, input: DecisionInput) =>
    apiClient.post<ApprovalOutcome>(`/approvals/${stageId}/approve`, input),
  reject: (stageId: string, input: DecisionInput) =>
    apiClient.post<ApprovalOutcome>(`/approvals/${stageId}/reject`, input),
  bulkApprove: (items: BulkDecisionItem[]) =>
    apiClient.post<BulkDecisionResult>("/approvals/bulk-approve", { items }),
  bulkReject: (items: BulkDecisionItem[]) =>
    apiClient.post<BulkDecisionResult>("/approvals/bulk-reject", { items }),
  getEligibility: (requestId: string) =>
    apiClient.get<ApprovalEligibility>(`/requests/${requestId}/approval-eligibility`),
};
