import { apiClient } from "@/lib/api/client";
import type {
  Request,
  RequestCreateInput,
  RequestListFilters,
  RequestPatchInput,
} from "@/types/request";
import type { AuditEntry } from "@/types/audit";
import type { WorkflowProgress, WorkflowStageDetail } from "@/types/workflow";

export interface ListRequestsParams extends RequestListFilters {
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

export const requestService = {
  list: (params: ListRequestsParams = {}) =>
    apiClient.getList<Request>(`/requests${buildQuery(params)}`),
  get: (id: string) => apiClient.get<Request>(`/requests/${id}`),
  create: (input: RequestCreateInput) => apiClient.post<Request>("/requests", input),
  update: (id: string, input: RequestPatchInput) =>
    apiClient.patch<Request>(`/requests/${id}`, input),
  withdraw: (id: string, expectedVersion: number) =>
    apiClient.delete<void>(`/requests/${id}${buildQuery({ expected_version: expectedVersion })}`),
  getWorkflowProgress: (id: string) => apiClient.get<WorkflowProgress>(`/requests/${id}/workflow`),
  getCurrentStage: (id: string) =>
    apiClient.get<WorkflowStageDetail | undefined>(`/requests/${id}/workflow/current`),
  getWorkflowHistory: (id: string) =>
    apiClient.get<WorkflowStageDetail[]>(`/requests/${id}/workflow/history`),
  getAuditTrail: (id: string) => apiClient.get<AuditEntry[]>(`/requests/${id}/audit-log`),
};
